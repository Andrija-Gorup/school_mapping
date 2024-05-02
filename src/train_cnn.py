import os
import time
import argparse
from collections import Counter
import torch

import sys
sys.path.insert(0, "../utils/")
import config_utils
import cnn_utils
import eval_utils
import wandb
import logging

# Get device
cwd = os.path.dirname(os.getcwd())
device = torch.device("cuda:1" if torch.cuda.is_available() else "cpu")
logging.info(f"Device: {device}")

SEED = 42

def main(c, exp_name="all"):    
    # Create experiment folder
    #exp_name = f"{c['iso_code']}_{c['config_name']}"
    exp_name = f"{exp_name}_{c['config_name']}"
    exp_dir = os.path.join(cwd, c["exp_dir"], exp_name)
    if not os.path.exists(exp_dir):
        os.makedirs(exp_dir)
    
    logname = os.path.join(exp_dir, f"{exp_name}.log")
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger()
    handler = logging.FileHandler(logname)
    handler.setLevel(logging.INFO)
    logger.addHandler(handler)
    logging.info(exp_name)

    # Set wandb configs
    #wandb.init(project="UNICEFv2", config=c)
    #wandb.run.name = exp_name
    #wandb.config = c
    
    # Load dataset
    phases = ["train", "test"]
    data, data_loader, classes = cnn_utils.load_dataset(config=c, phases=phases)
    logging.info(f"Train/test sizes: {len(data['train'])}/{len(data['test'])}")

    # Load model, optimizer, and scheduler
    model, criterion, optimizer, scheduler = cnn_utils.load_model(
        n_classes=len(classes),
        model_type=c["model"],
        pretrained=c["pretrained"],
        scheduler_type=c["scheduler"],
        optimizer_type=c["optimizer"],
        label_smoothing=c["label_smoothing"],
        lr=c["lr"],
        momentum=c["momentum"],
        gamma=c["gamma"],
        step_size=c["step_size"],
        patience=c["patience"],
        dropout=c["dropout"],
        device=device,
    )
    logging.info(model)

    # Instantiate wandb tracker
    #wandb.watch(model)

    # Commence model training
    n_epochs = c["n_epochs"]
    since = time.time()
    best_score = -1

    for epoch in range(1, n_epochs + 1):
        logging.info("\nEpoch {}/{}".format(epoch, n_epochs))

        # Train model
        cnn_utils.train(
            data_loader["train"],
            model,
            criterion,
            optimizer,
            device,
            pos_label=1,
            wandb=wandb,
            logging=logging
        )
        # Evauate model
        val_results, val_cm, val_preds = cnn_utils.evaluate(
            data_loader["test"], 
            classes, 
            model, 
            criterion, 
            device, 
            pos_label=1,
            wandb=wandb, 
            logging=logging
        )
        scheduler.step(val_results["f1_score"])

        # Save best model so far
        if val_results["f1_score"] > best_score:
            best_score = val_results["f1_score"]
            best_weights = model.state_dict()

            eval_utils._save_files(val_results, val_cm, exp_dir)
            model_file = os.path.join(exp_dir, f"{exp_name}.pth")
            torch.save(model.state_dict(), model_file)
        logging.info(f"Best F1 score: {best_score}")

        # Terminate if learning rate becomes too low
        learning_rate = optimizer.param_groups[0]["lr"]
        if learning_rate < 1e-10:
            break

    # Terminate trackers
    time_elapsed = time.time() - since
    logging.info(
        "Training complete in {:.0f}m {:.0f}s".format(
            time_elapsed // 60, time_elapsed % 60
        )
    )

    # Load best model
    model_file = os.path.join(exp_dir, f"{exp_name}.pth")
    model.load_state_dict(torch.load(model_file, map_location=device))
    model = model.to(device)

    # Calculate test performance using best model
    logging.info("\nTest Results")
    test_results, test_cm, test_preds = cnn_utils.evaluate(
        data_loader["test"], classes, model, criterion, device, pos_label=1, wandb=wandb, logging=logging
    )
    test_preds.to_csv(os.path.join(exp_dir, f"{exp_name}.csv"), index=False)

    # Save results in experiment directory
    eval_utils._save_files(test_results, test_cm, exp_dir)


def test(config, exp_name="all"):

    exp_name = f"{exp_name}_{config['config_name']}"
    exp_dir = os.path.join(cwd, c["exp_dir"], exp_name)

    phases = ["train", "test"]
    data, data_loader, classes = cnn_utils.load_dataset(config=c, phases=phases)

    model, criterion, optimizer, scheduler = cnn_utils.load_model(
        n_classes=len(classes),
        model_type=c["model"],
        pretrained=c["pretrained"],
        scheduler_type=c["scheduler"],
        optimizer_type=c["optimizer"],
        label_smoothing=c["label_smoothing"],
        lr=c["lr"],
        momentum=c["momentum"],
        gamma=c["gamma"],
        step_size=c["step_size"],
        patience=c["patience"],
        dropout=c["dropout"],
        device=device,
    )

    model_file = os.path.join(exp_dir, f"{exp_name}.pth")
    model.load_state_dict(torch.load(model_file, map_location=device))
    model = model.to(device)

    for iso_code in config["iso_codes"]:
        try:
            subresults_dir = os.path.join(exp_dir, iso_code)

            #print(data["test"].dataset.columns)
            subdata = data["test"].dataset[data["test"].dataset.iso == iso_code]
            #print(f"{iso_code}: {len(subdata)}")

            classes_dict = {config["pos_class"] : 1, config["neg_class"]: 0}
            transforms = cnn_utils.get_transforms(size=config["img_size"])
            dataset =  cnn_utils.SchoolDataset(
                    subdata
                    .sample(frac=1, random_state=SEED)
                    .reset_index(drop=True),
                    classes_dict,
                    transforms["test"]
            )


            data_loader =  torch.utils.data.DataLoader(
                    dataset,
                    batch_size=config["batch_size"],
                    num_workers=config["n_workers"],
                    shuffle=True,
                    drop_last=True
            )

            if len(data_loader) == 0:
                continue

            if not os.path.exists(subresults_dir):
                os.makedirs(subresults_dir)
            test_results, test_cm, test_preds = cnn_utils.evaluate(
                data_loader, classes, model, criterion, device, pos_label=1, wandb=wandb, logging=logging
            )
            test_preds.to_csv(os.path.join(subresults_dir, f"{iso_code}.csv"), index=False)

            # Save results in experiment directory
            eval_utils._save_files(test_results, test_cm, subresults_dir)
        except:
            print(f"error with code{iso_code}")

if __name__ == "__main__":
    # Parser
    parser = argparse.ArgumentParser(description="Model Training")
    parser.add_argument("--cnn_config", help="Config file", default="configs/cnn_configs/resnet18.yaml")
    parser.add_argument("--iso", help="ISO code", default=[
        'ATG', 'AIA', 'YEM', 'SEN', 'BWA', 'MDG', 'BEN', 'BIH', 'BLZ', 'BRB', 
        'CRI', 'DMA', 'GHA', 'GIN', 'GRD', 'HND', 'HUN', 'KAZ', 'KEN', 'KIR', 
        'KNA', 'LCA', 'MNG', 'MSR', 'MWI', 'NAM', 'NER', 'NGA', 'PAN', 'RWA', 
        'SLE', 'SLV', 'SSD', 'THA', 'TTO', 'UKR', 'UZB', 'VCT', 'VGB', 'ZAF', 
        'ZWE', 'BRA'
    ], nargs='+')
    parser.add_argument('-d', "--device", help="device", default="cuda:1")
    parser.add_argument("--test", action='store_true')
    parser.add_argument('-e', "--exp_name", default="all")
    args = parser.parse_args()

    device = torch.device(args.device)
    logging.info(f"config: {args.cnn_config}")
    logging.info(f"Args Device: {device}")
    logging.info(f"test: {args.test}")
    logging.info(f"exp_name: {args.exp_name}")

    # Load config
    config_file = os.path.join(cwd, args.cnn_config)
    c = config_utils.load_config(config_file)
    iso_codes = [
        "THA", 'KHM', 'LAO', 'IDN', 'PHL', 'MYS', 'MMR', 'BGD', 'BRN'
    ]
    c["iso_codes"] = iso_codes
    iso = iso_codes[0]

    

    if "name" in c: iso = c["name"]
    c["iso_code"] = iso
    log_c = {
        key: val for key, val in c.items() 
        if (key is not None) 
        and ('url' not in key) 
        and ('dir' not in key)
        and ('file' not in key)
    }
    #logging.info(log_c)

    test_flag = args.test
    if test_flag:
        test(c, args.exp_name)
    else:
        main(c, args.exp_name)