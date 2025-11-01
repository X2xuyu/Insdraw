from PIL import Image

img = Image.open("hka.png").convert("RGBA")
img.save("hka.ico", sizes=[(256,256), (128,128), (64,64), (32,32), (16,16)])
print("✅ hka.ico generated!")
