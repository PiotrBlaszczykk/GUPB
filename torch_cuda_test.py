import sys

try:
    import torch
except ImportError:
    print("ERROR: PyTorch nie jest zainstalowany w tym venvie.")
    sys.exit(1)

print("=== PYTHON ===")
print(sys.version)

print("\n=== TORCH ===")
print(f"torch.__version__: {torch.__version__}")
print(f"torch.version.cuda: {torch.version.cuda}")
print(f"torch.backends.cuda.is_built(): {torch.backends.cuda.is_built()}")
print(f"torch.cuda.is_available(): {torch.cuda.is_available()}")
print(f"torch.cuda.device_count(): {torch.cuda.device_count()}")

if torch.cuda.is_available():
    device_index = 0
    print("\n=== CUDA DEVICE ===")
    print(f"device name: {torch.cuda.get_device_name(device_index)}")
    print(f"device capability: {torch.cuda.get_device_capability(device_index)}")

    try:
        x = torch.rand(3, 3, device="cuda")
        y = torch.rand(3, 3, device="cuda")
        z = x @ y

        print("\n=== CUDA TEST ===")
        print("Udało się utworzyć tensory na GPU i wykonać mnożenie macierzy.")
        print(f"x.device: {x.device}")
        print(f"z.device: {z.device}")
        print("z =")
        print(z)

    except Exception as e:
        print("\nERROR: torch widzi CUDA, ale operacja na GPU wywaliła się.")
        print(type(e).__name__, e)
        sys.exit(2)
else:
    print("\nBRAK CUDA:")
    print("- torch działa, ale GPU nie jest dostępne.")
    print("- albo masz CPU-only build")
    print("- albo sterownik / wheel się nie zgadza")
    sys.exit(3)

print("\nOK: PyTorch działa i CUDA też działa.")