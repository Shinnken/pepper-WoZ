import qi
import time

session = qi.Session()
session.connect("tcp://127.0.0.1:9559")
led_controller = session.service("ALLeds")
print("dzik")
x = 0
while x < 10:
    led_controller.off("AllLeds")
    led_controller.on("AllLedsRed")
    time.sleep(1)
    led_controller.off("AllLeds")
    led_controller.on("AllLedsBlue")
    x += 1
    time.sleep(1)

