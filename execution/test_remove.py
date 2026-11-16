# execution/test_remove.py
import os

path = "test_write.txt"
try:
    with open(path, "w") as f:
        f.write("test")
    print(f"Successfully wrote to {path}")
    os.remove(path)
    print("Successfully removed text file from root!")
except Exception as e:
    print(f"Failed: {e}")
