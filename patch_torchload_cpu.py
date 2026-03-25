from pathlib import Path
import re

p = Path("lib/models/__init__.py")
if not p.exists():
    raise SystemExit("FAIL: không thấy lib/models/__init__.py")

s = p.read_text()

# Nếu đã patch rồi thì thôi
if "AUTO_MAP_LOCATION_WHAM" in s:
    print("OK: already patched")
    raise SystemExit(0)

# Tìm dòng: checkpoint = torch.load(cfg.TRAIN.CHECKPOINT)
pat = r"^(?P<indent>\s*)checkpoint\s*=\s*torch\.load\(\s*cfg\.TRAIN\.CHECKPOINT\s*\)\s*$"
m = re.search(pat, s, flags=re.M)
if not m:
    # Nếu không match, in gợi ý vị trí dòng torch.load để bạn tự xem
    hits = [line for line in s.splitlines() if "torch.load" in line]
    print("FAIL: không match được dòng checkpoint = torch.load(cfg.TRAIN.CHECKPOINT)")
    print("Các dòng có torch.load trong file:")
    for h in hits[:30]:
        print("  ", h)
    raise SystemExit(1)

indent = m.group("indent")
replacement = (
    f"{indent}# AUTO_MAP_LOCATION_WHAM: CPU fallback when CUDA is unavailable\n"
    f"{indent}map_loc = 'cpu' if (not torch.cuda.is_available() or getattr(cfg,'DEVICE','cuda')=='cpu') else None\n"
    f"{indent}checkpoint = torch.load(cfg.TRAIN.CHECKPOINT, map_location=map_loc) if map_loc else torch.load(cfg.TRAIN.CHECKPOINT)"
)

s2 = re.sub(pat, replacement, s, count=1, flags=re.M)
p.write_text(s2)
print("OK: patched lib/models/__init__.py (torch.load map_location=cpu when needed)")
