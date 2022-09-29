#!/usr/bin/env python3
import argparse
import os
import requests
import threading
import time
import yaml
from typing import Any, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont, ImageChops  # type: ignore
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
        self,
        deck: StreamDeck,
        font: str = "DejaVuSans.ttf",
        icon_color: Tuple[str, str] = ("#FFFFFF", "#777777"),
        fontsize: int = 14,
        brightness: int = 30,
        timeout: int = 60,
    ) -> None:
        self.deck: StreamDeck = deck
        self.__buttons: List[Button] = []
        self.__height: int = fontsize
        self.__font: ImageFont.ImageFont = ImageFont.truetype(
            os.path.join(ASSETS_PATH, font), self.__height
        )
        self.__icon_colors = icon_color
        self.__closed = False
        self.__timeout = timeout
        self.__lastbutton = time.time()

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

    def add_buttons(self, buttons: Sequence[Button]) -> None:
        # TODO: Handle having too many buttons.
        self.__buttons.extend(buttons)
        self.refresh()

    def refresh(self) -> None:
        for i in range(self.deck.key_count()):
            self.update_key_image(i)

        if self.__timeout > 0 and ((self.__lastbutton + self.__timeout) < time.time()):
            # Screen timed out
            with self.deck:
                self.deck.set_brightness(0)

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

    def split_word(self, word: str) -> Tuple[str, str]:
        tot = len(word)
        loc = int(len(word) / 2)
        sub = 0

        while sub <= loc:
            if word[loc - sub].isupper():
                return (word[: (loc - sub)], word[(loc - sub) :])
            if (loc + sub) < tot and word[loc + sub].isupper():
                return (word[: (loc + sub)], word[(loc + sub) :])

            sub += 1

        # Just split evenly
        return (word[:loc], word[loc:])

    def get_wrapped_text(
        self, label_text: str, line_length: int
    ) -> List[Tuple[str, int]]:
        lines = [""]
        for word in label_text.split():
            oldline = lines[-1].strip()
            line = f"{lines[-1]} {word}".strip()

            if self.__font.getlength(line) <= line_length:
                # We have enough room to add this word to the line.
                lines[-1] = line
            else:
                if oldline:
                    # There was something on the previous line, so start a new one.
                    lines.append(word)
                else:
                    # There was nothing on the line, this word doesn't fit, so split it.
                    w1, w2 = self.split_word(word)

                    lines[-1] = f"{lines[-1]} {w1}".strip()
                    lines.append(w2)

        return [(ln, self.__font.getlength(ln)) for ln in lines if ln]

    def render_key_image(
        self, icon_filename: str, icon_color: str, label_text: str
    ) -> StreamDeckImage:
        icon = Image.open(icon_filename)
        iconimage = PILHelper.create_scaled_image(
            self.deck, icon, margins=[0, 0, 20, 0]
        )
        colorimage = Image.new("RGB", iconimage.size, icon_color)
        image = ImageChops.multiply(iconimage, colorimage)

        draw = ImageDraw.Draw(image)

        lines = self.get_wrapped_text(label_text, image.width)
        numlines = len(lines)
        if numlines < 2:
            numlines = 2

        for lno, (line, width) in enumerate(lines):
            draw.text(
                (
                    (image.width - width) / 2,
                    image.height - (5 + (self.__height * (numlines - lno))),
                ),
                text=line,
                font=self.__font,
                anchor="lt",
                fill="white",
            )

        return PILHelper.to_native_format(self.deck, image)

    def update_key_image(self, key: int) -> None:
        if key < 0 or key >= len(self.buttons):
            key_style = {
                "icon": os.path.join(ASSETS_PATH, "Blank.png"),
                "label": "",
                "color": "#000000",
            }
        else:
            state = self.__buttons[key].state
            key_style = {
                "icon": os.path.join(
                    ASSETS_PATH,
                    "{}.png".format("On" if state else "Off"),
                ),
                "label": self.__buttons[key].label,
                "color": self.__icon_colors[0] if state else self.__icon_colors[1],
            }

        image = self.render_key_image(
            key_style["icon"], key_style["color"], key_style["label"]
        )

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

        if self.__timeout > 0 and (self.__lastbutton + self.__timeout < time.time()):
            # Screen timed out, need to wake
            with self.deck:
                self.deck.set_brightness(self.__brightness)
        elif key >= 0 and key < len(self.buttons):
            self.__buttons[key].state = not self.__buttons[key].state

        self.__lastbutton = time.time()
        self.update_key_image(key)


class Config:
    def __init__(self, file: str) -> None:
        with open(file, "r") as stream:
            yamlfile = yaml.safe_load(stream)

            hass = yamlfile.get("homeassistant", {})
            self.homeassistant_uri: Optional[str] = hass.get("url", None)
            self.homeassistant_token: Optional[str] = hass.get("token", None)
            self.homeassistant_entities: List[str] = []

            for entry in hass.get("entities", []) or []:
                self.homeassistant_entities.append(entry)

            font = yamlfile.get("font", {})
            self.font_size = int(font.get("size", 14))
            self.font_face = font.get("face", "DejaVuSans.ttf")

            screen = yamlfile.get("screen", {})
            self.screen_brightness = int(screen.get("brightness", 30))
            self.screen_timeout = int(screen.get("timeout", 60))

            icon = yamlfile.get("icon", {})
            icon_color = icon.get("color", {})

            # PyYAML does this insanely stupid thing where it converts *KEYS* to booleans
            # based on an internal pattern. What the unholy fuck, this is some PHP shit.
            self.icon_color_on = str(
                icon_color.get(True, icon_color.get("on", "#FFFFFF"))
            )
            self.icon_color_off = str(
                icon_color.get(False, icon_color.get("off", "#777777"))
            )


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

        # Set initial screen brightness.
        driver = StreamDeckDriver(
            found_deck,
            font=config.font_face,
            fontsize=config.font_size,
            icon_color=(config.icon_color_on, config.icon_color_off),
            brightness=config.screen_brightness,
            timeout=config.screen_timeout,
        )

        try:
            if config.homeassistant_uri and config.homeassistant_token:
                driver.add_buttons(
                    [
                        HomeAssistantButton(
                            config.homeassistant_uri,
                            config.homeassistant_token,
                            entity,
                        )
                        for entity in config.homeassistant_entities
                    ]
                )

            while not driver.closed:
                time.sleep(1.0)
                driver.refresh()
        except KeyboardInterrupt:
            print("Closing device due to Ctrl-C request.")
            driver.close()

    # Wait until all application threads have terminated (for this example,
    # this is when all deck handles are closed).
    for t in threading.enumerate():
        try:
            t.join()
        except RuntimeError:
            pass
