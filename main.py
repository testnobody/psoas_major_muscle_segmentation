import argparse
import os
import os.path as osp

from tqdm import tqdm
import torch
import torch.optim as optim
import torch.nn as nn
from torch.utils.tensorboard import SummaryWriter

from modules.model.unet import UNet
from modules.data import build_dataloader
from modules.config import cfg


def parse_args():
    parser = argparse.ArgumentParser(
        description="pasoas major muscle segmentations"
    )
    parser.add_argument(
        "--cfg",
        type=str,
        metavar="FILE",
        dest="config_file",
        default="configs/UNET.yaml",
        help="config file path",
    )
    parser.add_argument(
        "opt",
        default=None,
        nargs=argparse.REMAINDER,
        help="use command line to modify param",
    )

    args = parser.parse_args()
    return args


def dice_coeff(input, target):
    s = 0
    eps = 1e-4

    for c in zip(input, target):
        inter = torch.dot(c[0].view(-1), c[1].view(-1))
        union = torch.sum(c[0]) + torch.sum(c[1]) + eps

        t = (2 * inter.float() + eps) / union.float()
        s += t

    return s / len(input)


def evaluate(model, test_loader):
    model.eval()

    dice = 0
    n_test = len(test_loader)
    tbar = tqdm(test_loader, ascii=True)
    for data_batch in tbar:
        if torch.cuda.is_available():
            data_batch = {
                k: v.cuda(non_blocking=True)
                for k, v in data_batch.items()
            }

        with torch.no_grad():
            mask_pred = model(data_batch["image"])

        pred = torch.sigmoid(mask_pred)
        pred = (pred > 0.5).float()
        dice += dice_coeff(pred, data_batch["label"])

    return dice / n_test


def train(cfg):
    train_loader, test_loader = build_dataloader(cfg.DATA)
    criterion = nn.BCEWithLogitsLoss()
    model = UNet(
        n_channels=cfg.MODEL.N_CHANNELS,
        n_class=cfg.MODEL.N_CLASS
    )
    optimizer = optim.RMSprop(
        model.parameters(),
        lr=cfg.TRAIN.LR,
        weight_decay=cfg.TRAIN.WEIGHT_DECAY,
        momentum=cfg.TRAIN.MOMENTUM,
    )

    if torch.cuda.is_available():
        model = model.cuda()

    log_dir = osp.join(cfg.OUTPUT_DIR, "log")
    writer = SummaryWriter(log_dir=log_dir)

    global_step = 0
    for epoch in range(cfg.TRAIN.EPOCH):
        model.train()

        cur_epoch = epoch + 1
        global_step += 1
        epoch_loss = 0

        tbar = tqdm(train_loader, ascii=True)
        for data_batch in tbar:
            tbar.set_description("Epoch {}".format(cur_epoch))

            if torch.cuda.is_available():
                data_batch = {
                    k: v.cuda(non_blocking=True)
                    for k, v in data_batch.items()
                }

            image = data_batch["image"].unsqueeze(dim=1)
            label = data_batch["label"].unsqueeze(dim=1)

            logits = model(image)
            loss = criterion(logits, label)
            epoch_loss += loss.item()

            writer.add_scalar(
                "Loss/train", loss.item(), global_step
            )
            optimizer.zero_grad()
            loss.backward()
            nn.utils.clip_grad_value_(model.parameters(), 0.1)
            optimizer.step()

        if global_step % cfg.TEST_STEP == 0:
            test_score = evaluate(model, test_loader)
            print("Test Dice Coeff: {}".format(test_score))
            writer.add_scalar(
                "Dice/test", test_score, global_step
            )
        print("Training loss: {}".format(epoch_loss))

    writer.close()
    print("TRAINING DONE.")


def main():
    args = parse_args()

    cfg.merge_from_file(args.config_file)
    cfg.merge_from_list(args.opt)
    cfg.freeze()
    print(cfg)

    if cfg.OUTPUT_DIR:
        output_dir = osp.join(".", cfg.OUTPUT_DIR)
        os.makedirs(output_dir, exist_ok=True)

    train(cfg)
    exit(0)


if __name__ == "__main__":
    main()
