from PyQt6.QtCore import QSettings

APP_NAME = "ACCELA Next"
ORG_NAME = "Tachibana Labs"


def get_settings():

    return QSettings(ORG_NAME, APP_NAME)
