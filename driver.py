#!/usr/bin/env python3
import argparse
import os
import requests
import threading
import time
import yaml
from typing import Any, List, Optional

from PIL import Image, ImageDraw, ImageFont  # type: ignore
from StreamDeck.DeviceManager import DeviceManager  # type: ignore
from StreamDeck.ImageHelpers import PILHelper  # type: ignore
from StreamDeck.Transport.Transport import TransportError  # type: ignore


# Folder location of image assets used by this example.
ASSETS_PATH = os.path.join(os.path.dirname(__file__), "Assets")


# Since the library is untyped.
StreamDeck = Any
StreamDeckImage = Any


class Button:
    def __init__(self, label: str) -> None:
        self.label = label

    @property
    def state(self) -> Optional[bool]:
        return None

    @state.setter
    def state(self, newstate: bool) -> None:
        raise NotImplementedError("Not implemented!")


class HomeAssistantButton(Button):
    def __init__(self, uri: str, token: str, entity: str) -> None:
        super().__init__(entity)
        self.uri = uri + ("/" if uri[-1] != "/" else "")
        self.token = token
        self.entity = entity

    @property
    def state(self) -> Optional[bool]:
        url = f"{self.uri}api/states/{self.entity}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "content-type": "application/json",
        }
        response = requests.get(url, headers=headers)
        try:
            data = response.json()
            if data.get("entity_id", None) != self.entity:
                return None

            self.label = data.get("attributes", {}).get("friendly_name", self.label)
            return bool(data.get("state", "off").lower() == "on")
        except Exception:
            return None

    @state.setter
    def state(self, newstate: bool) -> None:
        url = f"{self.uri}api/services/switch/turn_{'off' if self.state else 'on'}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "content-type": "application/json",
        }
        request = {
            "entity_id": self.entity,
        }
        requests.post(url, headers=headers, json=request)


class StreamDeckDriver:
    def __init__(
        self, deck: StreamDeck, font: str = "DejaVuSans.ttf", brightness: int = 30
    ) -> None:
        self.deck: StreamDeck = deck
        self.__buttons: List[Button] = []
        self.__font: ImageFont.ImageFont = ImageFont.truetype(
            os.path.join(ASSETS_PATH, font), 14
        )
        self.__closed = False

        # Set up a key change callback
        deck.set_key_callback(self.key_change_callback)

        # Default the brightness
        self.__brightness: int = brightness
        self.brightness = brightness

        # Render all buttons
        self.refresh()

    @property
    def brightness(self) -> int:
        return self.__brightness

    @brightness.setter
    def brightness(self, newval: int) -> None:
        self.__brightness = newval

        try:
            with self.deck:
                self.deck.set_brightness(self.__brightness)
        except TransportError:
            pass

    @property
    def buttons(self) -> List[Button]:
        return list(self.__buttons)

    @property
    def closed(self) -> bool:
        return self.__closed

    def add_button(self, button: Button) -> None:
        # TODO: Handle having too many buttons.
        self.__buttons.append(button)
        self.refresh()

    def refresh(self) -> None:
        for i in range(self.deck.key_count()):
            self.update_key_image(i)

    def close(self) -> None:
        self.__closed = True

        try:
            with self.deck:
                # Reset deck, clearing all button images.
                self.deck.reset()

                # Close deck handle, terminating internal worker threads.
                self.deck.close()
        except TransportError:
            pass

    def get_wrapped_text(self, label_text: str, line_length: int) -> str:
        lines = [""]
        for word in label_text.split():
            line = f"{lines[-1]} {word}".strip()
            if self.__font.getlength(line) <= line_length:
                lines[-1] = line
            else:
                lines.append(word)
        return "\n".join([ln for ln in lines if ln])

    def render_key_image(self, icon_filename: str, label_text: str) -> StreamDeckImage:
        icon = Image.open(icon_filename)
        image = PILHelper.create_scaled_image(self.deck, icon, margins=[0, 0, 20, 0])
        draw = ImageDraw.Draw(image)
        text = self.get_wrapped_text(label_text, image.width)
        numlines = len(text.split())

        draw.multiline_text(
            (image.width / 2, image.height - (5 + (14 * (numlines - 1)))),
            text=text,
            font=self.__font,
            anchor="ms",
            fill="white",
        )

        return PILHelper.to_native_format(self.deck, image)

    def update_key_image(self, key: int) -> None:
        if key < 0 or key >= len(self.buttons):
            key_style = {
                "icon": os.path.join(ASSETS_PATH, "Blank.png"),
                "label": "",
            }
        else:
            key_style = {
                "icon": os.path.join(
                    ASSETS_PATH,
                    "{}.png".format("On" if self.__buttons[key].state else "Off"),
                ),
                "label": self.__buttons[key].label,
            }

        image = self.render_key_image(key_style["icon"], key_style["label"])

        try:
            with self.deck:
                self.deck.set_key_image(key, image)
        except TransportError:
            pass

    def key_change_callback(self, deck: StreamDeck, key: int, pressed: bool) -> None:
        if deck is not self.deck:
            raise Exception("Logic error!")
        if not pressed:
            # Don't care about release actions
            return

        if key >= 0 and key < len(self.buttons):
            self.__buttons[key].state = not self.__buttons[key].state
        self.update_key_image(key)


class Config:
    def __init__(self, file: str) -> None:
        with open(file, "r") as stream:
            yamlfile = yaml.safe_load(stream)

            hass = yamlfile.get("homeassistant", {})
            self.homeassistant_uri = hass.get("url", None)
            self.homeassistant_token = hass.get("token", None)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Control a series of switches from a StreamDeck."
    )
    parser.add_argument(
        "--config",
        metavar="CONFIG",
        type=str,
        default="config.yaml",
        help="Configuration file for switches. Defaults to config.yaml",
    )
    args = parser.parse_args()
    config = Config(args.config)

    streamdecks = DeviceManager().enumerate()

    print("Found {} Stream Deck(s).".format(len(streamdecks)))

    for found_deck in streamdecks:
        # This example only works with devices that have screens.
        if not found_deck.is_visual():
            continue

        found_deck.open()
        found_deck.reset()

        print(
            "Opened '{}' device (serial number: '{}', fw: '{}')".format(
                found_deck.deck_type(),
                found_deck.get_serial_number(),
                found_deck.get_firmware_version(),
            )
        )

        # Set initial screen brightness to 30%.
        driver = StreamDeckDriver(found_deck, brightness=30)

        try:
            driver.add_button(
                HomeAssistantButton(
                    config.homeassistant_uri,
                    config.homeassistant_token,
                    "switch.bishi_bashi",
                )
            )

            while not driver.closed:
                time.sleep(1.0)
                driver.refresh()
        except KeyboardInterrupt:
            driver.close()

    # Wait until all application threads have terminated (for this example,
    # this is when all deck handles are closed).
    for t in threading.enumerate():
        try:
            t.join()
        except RuntimeError:
            pass
