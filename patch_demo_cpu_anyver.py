from pathlib import Path
import re

p = Path("demo.py")
s = p.read_text()

# 0) Nếu đã patch rồi thì thôi
if "AUTO_CPU_FALLBACK_WHAM" in s:
    print("OK: demo.py already patched")
    raise SystemExit(0)

# 1) Đảm bảo có import os (để set CUDA_VISIBLE_DEVICES)
if not re.search(r'^\s*import\s+os\b', s, flags=re.M):
    # chèn sau cụm import đầu file (an toàn hơn chèn đầu file)
    m = re.search(r'^(?:from\s+\S+\s+import\s+\S+|import\s+\S+).*\n', s, flags=re.M)
    if m:
        insert_at = m.end()
        s = s[:insert_at] + "import os\n" + s[insert_at:]
    else:
        s = "import os\n" + s

# 2) Xoá các dòng “GPU name/feat” kiểu cũ để khỏi gọi torch.cuda.* khi không có CUDA
s = re.sub(r"^\s*logger\.\w+\(.*torch\.cuda\.get_device_name.*\)\s*\n", "", s, flags=re.M)
s = re.sub(r"^\s*logger\.\w+\(.*torch\.cuda\.get_device_properties.*\)\s*\n", "", s, flags=re.M)

# 3) Tìm dòng merge demo.yaml (linh hoạt nhiều kiểu viết), rồi chèn CPU fallback ngay sau đó
pat_list = [
    r"(cfg\.merge_from_file\(\s*['\"]configs/yamls/demo\.yaml['\"]\s*\)\s*\n)",
    r"(cfg\.merge_from_file\(\s*['\"].*demo\.yaml['\"]\s*\)\s*\n)",
]
m = None
for pat in pat_list:
    m = re.search(pat, s)
    if m:
        pat_used = pat
        break

if not m:
    raise SystemExit("FAIL: Không tìm thấy cfg.merge_from_file(...demo.yaml...) trong demo.py để chèn CPU fallback.")

insert = (
    "\n# AUTO_CPU_FALLBACK_WHAM\n"
    "# Auto CPU fallback on macOS Docker (no NVIDIA CUDA runtime)\n"
    "if not torch.cuda.is_available():\n"
    "    cfg.DEVICE = 'cpu'\n"
    "    os.environ['CUDA_VISIBLE_DEVICES'] = ''\n"
    "    try:\n"
    "        import torch.backends.cudnn as cudnn\n"
    "        cudnn.enabled = False\n"
    "    except Exception:\n"
    "        pass\n"
    "    logger.warning('CUDA not available -> switch cfg.DEVICE=cpu')\n"
    "# END_AUTO_CPU_FALLBACK_WHAM\n\n"
)

s = re.sub(pat_used, r"\1" + insert, s, count=1)

p.write_text(s)
print("OK: patched demo.py with CPU fallback (any version)")
