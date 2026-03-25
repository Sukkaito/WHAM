from pathlib import Path
import re

p = Path("demo.py")
s = p.read_text()

# Nếu đã patch rồi thì thôi
if "Auto CPU fallback (macOS Docker has no CUDA)" in s:
    print("✅ demo.py already patched")
    raise SystemExit(0)

# Replace block GPU logging (đúng theo demo.py upstream)
old = (
"cfg = get_cfg_defaults()\n"
"cfg.merge_from_file('configs/yamls/demo.yaml')\n"
"logger.info(f'GPU name -> {torch.cuda.get_device_name()}')\n"
"logger.info(f'GPU feat -> {torch.cuda.get_device_properties(\"cuda\")}')\n"
)

new = (
"cfg = get_cfg_defaults()\n"
"cfg.merge_from_file('configs/yamls/demo.yaml')\n"
"\n"
"# ---- Auto CPU fallback (macOS Docker has no CUDA) ----\n"
"if not torch.cuda.is_available():\n"
"    cfg.DEVICE = 'cpu'\n"
"    os.environ['CUDA_VISIBLE_DEVICES'] = ''\n"
"    logger.warning('CUDA not available -> switch cfg.DEVICE=cpu')\n"
"else:\n"
"    logger.info(f'GPU name -> {torch.cuda.get_device_name(0)}')\n"
"    logger.info(f'GPU feat -> {torch.cuda.get_device_properties(0)}')\n"
"# -----------------------------------------------------\n"
)

if old not in s:
    raise SystemExit("❌ Không match được block GPU logging trong demo.py (file khác version). Hãy mở demo.py và patch thủ công theo mẫu ở trên.")

s = s.replace(old, new)

# Thêm log tiến độ preprocess (để không tưởng treo)
# Chèn counter i vào while loop
s = s.replace(
"bar = Bar('Preprocess: 2D detection and SLAM', fill='#', max=length)\n"
"while (cap.isOpened()):\n",
"bar = Bar('Preprocess: 2D detection and SLAM', fill='#', max=length)\n"
"i = 0\n"
"while (cap.isOpened()):\n"
)

s = s.replace(
"bar.next()\n",
"i += 1\n"
"if i % 50 == 0:\n"
"    logger.info(f'Preprocess frame {i}/{length}')\n"
"bar.next()\n"
)

p.write_text(s)
print("✅ Patched demo.py: CPU fallback + preprocess progress logs")
