"""TruFor inference wrapper with auto-resize and heatmap visualization."""
import sys, os
import argparse
import numpy as np
from glob import glob
from PIL import Image

import torch
from torch.nn import functional as F

TRUFOR_ROOT = os.path.join(os.path.dirname(__file__), 'TruFor', 'TruFor_train_test')
sys.path.insert(0, TRUFOR_ROOT)
sys.path.insert(0, os.path.join(TRUFOR_ROOT, '..'))

from lib.config import config, update_config
from lib.utils import get_model


def select_device():
    if torch.cuda.is_available():
        return 'cuda:0'
    elif torch.backends.mps.is_available():
        return 'mps'
    return 'cpu'


def load_model(device, model_file):
    orig_cwd = os.getcwd()
    os.chdir(TRUFOR_ROOT)
    try:
        class Args:
            experiment = 'trufor_ph3'
            gpu = 0
            opts = ['TEST.MODEL_FILE', model_file]
        update_config(config, Args())
    finally:
        os.chdir(orig_cwd)

    checkpoint = torch.load(model_file, map_location='cpu', weights_only=False)
    print(f'Model loaded (epoch {checkpoint["epoch"]}), device: {device}')

    model = get_model(config)
    model.load_state_dict(checkpoint['state_dict'])
    model = model.to(device)
    model.eval()
    return model


def _make_blend_weights(tile_h, tile_w, overlap):
    """Generate linear blending weights: 1 in center, ramp to 0 at edges within overlap."""
    wy = np.ones(tile_h, dtype=np.float32)
    wx = np.ones(tile_w, dtype=np.float32)
    if overlap > 0:
        ramp = np.linspace(0, 1, overlap, dtype=np.float32)
        wy[:overlap] = np.minimum(wy[:overlap], ramp)
        wy[-overlap:] = np.minimum(wy[-overlap:], ramp[::-1])
        wx[:overlap] = np.minimum(wx[:overlap], ramp)
        wx[-overlap:] = np.minimum(wx[-overlap:], ramp[::-1])
    return wy[:, None] * wx[None, :]


def _infer_tile(model, tile_rgb, device):
    """Run model on a single tile tensor, return numpy outputs."""
    tile_tensor = torch.tensor(tile_rgb).unsqueeze(0).to(device)
    with torch.no_grad():
        pred, conf, det, npp = model(tile_tensor, save_np=True)

    score = torch.sigmoid(det).item() if det is not None else None
    loc = F.softmax(torch.squeeze(pred, 0), dim=0)[1].cpu().numpy()
    c = torch.sigmoid(torch.squeeze(conf, 0))[0].cpu().numpy() if conf is not None else None
    n = torch.squeeze(npp, 0)[0].cpu().numpy() if npp is not None else None
    return loc, c, n, score


def run_tiled(model, image_path, device, tile_size=1024, overlap=256):
    """Tile-based inference for images too large to fit in GPU memory."""
    img = Image.open(image_path).convert('RGB')
    orig_size = img.size
    full_rgb = np.array(img).transpose(2, 0, 1).astype(np.float32) / 256.0
    _, H, W = full_rgb.shape
    stride = tile_size - overlap

    ys = list(range(0, H - tile_size, stride)) + [H - tile_size]
    xs = list(range(0, W - tile_size, stride)) + [W - tile_size]
    ys = sorted(set(max(0, y) for y in ys))
    xs = sorted(set(max(0, x) for x in xs))

    accum_map = np.zeros((H, W), dtype=np.float64)
    accum_conf = np.zeros((H, W), dtype=np.float64)
    accum_np = np.zeros((H, W), dtype=np.float64)
    accum_w = np.zeros((H, W), dtype=np.float64)
    max_score = 0.0
    n_tiles = len(ys) * len(xs)

    for i, y in enumerate(ys):
        for j, x in enumerate(xs):
            y2 = min(y + tile_size, H)
            x2 = min(x + tile_size, W)
            y1 = y2 - tile_size
            x1 = x2 - tile_size

            tile_rgb = full_rgb[:, y1:y2, x1:x2]
            loc, c, n, score = _infer_tile(model, tile_rgb, device)

            w = _make_blend_weights(y2 - y1, x2 - x1, overlap)
            accum_map[y1:y2, x1:x2] += loc * w
            if c is not None:
                accum_conf[y1:y2, x1:x2] += c * w
            if n is not None:
                accum_np[y1:y2, x1:x2] += n * w
            accum_w[y1:y2, x1:x2] += w

            if score is not None and score > max_score:
                max_score = score

            if device == 'mps':
                torch.mps.empty_cache()

            print(f'    tile [{i * len(xs) + j + 1}/{n_tiles}] y={y1}:{y2} x={x1}:{x2} score={score:.4f}')

    safe_w = np.where(accum_w > 0, accum_w, 1.0)
    loc_map = (accum_map / safe_w).astype(np.float32)
    conf_map = (accum_conf / safe_w).astype(np.float32)
    np_map = (accum_np / safe_w).astype(np.float32)

    return {
        'score': max_score,
        'map': loc_map,
        'conf': conf_map,
        'np++': np_map,
        'orig_size': orig_size,
        'infer_size': f'{orig_size[0]}x{orig_size[1]} (tiled)',
    }


def run_single(model, image_path, device, max_size=1792, tile_size=1024, overlap=256):
    img = Image.open(image_path).convert('RGB')
    orig_size = img.size
    w, h = img.size

    if max(w, h) > max_size:
        return run_tiled(model, image_path, device, tile_size=tile_size, overlap=overlap)

    rgb = np.array(img).transpose(2, 0, 1).astype(np.float32) / 256.0
    rgb = torch.tensor(rgb).unsqueeze(0).to(device)

    with torch.no_grad():
        pred, conf, det, npp = model(rgb, save_np=True)

    score = torch.sigmoid(det).item() if det is not None else None
    loc_map = F.softmax(torch.squeeze(pred, 0), dim=0)[1].cpu().numpy()
    conf_map = torch.sigmoid(torch.squeeze(conf, 0))[0].cpu().numpy() if conf is not None else None
    np_map = torch.squeeze(npp, 0)[0].cpu().numpy() if npp is not None else None

    return {
        'score': score,
        'map': loc_map,
        'conf': conf_map,
        'np++': np_map,
        'orig_size': orig_size,
        'infer_size': img.size,
    }


def save_heatmap(image_path, result, output_path):
    import matplotlib
    matplotlib.use('agg')
    import matplotlib.pyplot as plt

    img = Image.open(image_path).convert('RGB')
    loc_map = result['map']
    conf_map = result['conf']
    score = result['score']

    cols = 3
    fig, axs = plt.subplots(1, cols, figsize=(cols * 5, 5))
    fig.suptitle(f'Score: {score:.4f} | Infer size: {result["infer_size"]}', fontsize=14)

    for ax in axs:
        ax.axis('off')

    axs[0].imshow(img)
    axs[0].set_title('Original')

    axs[1].imshow(loc_map, cmap='RdBu_r', clim=[0, 1])
    axs[1].set_title('Localization Map')

    if conf_map is not None:
        axs[2].imshow(conf_map, cmap='gray', clim=[0, 1])
        axs[2].set_title('Confidence Map')

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f'  Heatmap saved: {output_path}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-i', '--input', required=True, help='image file or directory')
    parser.add_argument('-o', '--output', default='output', help='output directory')
    parser.add_argument('--max-size', type=int, default=1792, help='max dimension before tiled inference')
    parser.add_argument('--weights', default=os.path.join(TRUFOR_ROOT, 'pretrained_models', 'trufor.pth.tar'))
    args = parser.parse_args()

    device = select_device()
    model = load_model(device, args.weights)

    if os.path.isfile(args.input):
        images = [args.input]
    else:
        images = sorted([os.path.join(args.input, f) for f in os.listdir(args.input)
                         if f.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp', '.tiff'))])

    os.makedirs(args.output, exist_ok=True)

    for img_path in images:
        name = os.path.basename(img_path)
        print(f'Processing: {name}')
        result = run_single(model, img_path, device, max_size=args.max_size)
        print(f'  Score: {result["score"]:.4f} | {result["orig_size"]} -> {result["infer_size"]}')
        if device == 'mps':
            torch.mps.empty_cache()

        npz_path = os.path.join(args.output, name + '.npz')
        np.savez(npz_path, **{k: v for k, v in result.items() if isinstance(v, np.ndarray)},
                 score=result['score'])

        heatmap_path = os.path.join(args.output, os.path.splitext(name)[0] + '_heatmap.png')
        save_heatmap(img_path, result, heatmap_path)

    print(f'\nDone! {len(images)} images processed.')


if __name__ == '__main__':
    main()
