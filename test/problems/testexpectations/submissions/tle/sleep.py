import time

x = int(input())
start = time.time()
while time.time() - start < x:
    # busy wait
    pass
# time.sleep(max(0, x))
print(x)
