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


class BlankButton(Button):
    def __init__(self) -> None:
        super().__init__("")

    @property
    def state(self) -> Optional[bool]:
        return False

    @state.setter
    def state(self, newstate: bool) -> None:
        pass


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
        icon_image: Tuple[str, str, str] = ("On.png", "Off.png", "Blank.png"),
        icon_color: Tuple[str, str] = ("#FFFFFF", "#777777"),
        fontsize: int = 14,
        brightness: int = 30,
        rotation: int = 0,
        timeout: int = 60,
    ) -> None:
        self.deck: StreamDeck = deck
        self.__buttons: List[Button] = []
        self.__height: int = fontsize
        self.__font: ImageFont.ImageFont = ImageFont.truetype(
            os.path.join(ASSETS_PATH, font), self.__height
        )
        self.__icon_colors = icon_color
        self.__icon_images = icon_image
        self.__closed = False
        self.__timeout = timeout
        self.__lastbutton = time.time()
        self.__rotation = rotation

        # Double-check bounds, also allow negative rotation since its easy
        # to convert to positive rotation
        if self.__rotation not in {0, 90, 180, 270, -90, -180, -270}:
            raise Exception(
                f"Invalid rotation value {rotation}, must be a right angle!"
            )
        if self.__rotation < 0:
            self.__rotation += 360

        # Set up a key change callback
        deck.set_key_callback(self.__key_change_callback)

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
            self.__update_key_image(i)

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

    def __split_word(self, word: str) -> Tuple[str, str]:
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

    def __get_wrapped_text(
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
                    w1, w2 = self.__split_word(word)

                    lines[-1] = f"{lines[-1]} {w1}".strip()
                    lines.append(w2)

        return [(ln, self.__font.getlength(ln)) for ln in lines if ln]

    def __render_key_image(
        self, icon_filename: str, icon_color: str, label_text: str
    ) -> StreamDeckImage:
        icon = Image.open(icon_filename)
        iconimage = PILHelper.create_scaled_image(
            self.deck, icon, margins=[0, 0, 20, 0]
        )
        colorimage = Image.new("RGB", iconimage.size, icon_color)
        image = ImageChops.multiply(iconimage, colorimage)

        draw = ImageDraw.Draw(image)

        lines = self.__get_wrapped_text(label_text, image.width)
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

        if self.__rotation != 0:
            w, h = image.size
            if w != h:
                raise Exception("Unexpected non-square image?")

            # The rotation is "backwards" because we are specifying the rotation
            # of the entire screen, not the individual images.
            image = image.rotate(self.__rotation, expand=False)

        return PILHelper.to_native_format(self.deck, image)

    def __virtual_to_physical(self, virtual_key: int) -> int:
        # Necessary because the StreamDeck library is untyped.
        rows: int
        cols: int

        if self.__rotation == 0:
            return virtual_key
        elif self.__rotation == 90:
            with self.deck:
                rows, cols = self.deck.key_layout()

            whichrow = (rows - 1) - (virtual_key % rows)
            whichcol = int(virtual_key / rows)

            return (cols * whichrow) + whichcol
        elif self.__rotation == 180:
            with self.deck:
                return int(self.deck.key_count() - 1) - virtual_key
        else:
            with self.deck:
                rows, cols = self.deck.key_layout()

            whichrow = virtual_key % rows
            whichcol = (cols - 1) - int(virtual_key / rows)

            return (cols * whichrow) + whichcol

    def __physical_to_virtual(self, physical_key: int) -> int:
        # Necessary because the StreamDeck library is untyped.
        rows: int
        cols: int

        if self.__rotation == 0:
            return physical_key
        elif self.__rotation == 90:
            with self.deck:
                rows, cols = self.deck.key_layout()

            whichrow = int(physical_key / cols)
            whichcol = physical_key % cols

            return ((rows - 1) - whichrow) + (rows * whichcol)

        elif self.__rotation == 180:
            with self.deck:
                return int(self.deck.key_count() - 1) - physical_key
        else:
            with self.deck:
                rows, cols = self.deck.key_layout()

            whichrow = int(physical_key / cols)
            whichcol = physical_key % cols

            return whichrow + (((cols - 1) - whichcol) * rows)

    def __update_key_image(self, virtual_key: int) -> None:
        if (
            virtual_key < 0
            or virtual_key >= len(self.__buttons)
            or isinstance(self.__buttons[virtual_key], BlankButton)
        ):
            key_style = {
                "icon": os.path.join(ASSETS_PATH, self.__icon_images[2]),
                "label": "",
                "color": "#FFFFFF",
            }
        else:
            state = self.__buttons[virtual_key].state
            key_style = {
                "icon": os.path.join(
                    ASSETS_PATH,
                    self.__icon_images[0] if state else self.__icon_images[1],
                ),
                "label": self.__buttons[virtual_key].label,
                "color": self.__icon_colors[0] if state else self.__icon_colors[1],
            }

        image = self.__render_key_image(
            key_style["icon"], key_style["color"], key_style["label"]
        )

        try:
            with self.deck:
                self.deck.set_key_image(self.__virtual_to_physical(virtual_key), image)
        except TransportError:
            pass

    def __key_change_callback(
        self, deck: StreamDeck, physical_key: int, pressed: bool
    ) -> None:
        if deck is not self.deck:
            raise Exception("Logic error!")
        if not pressed:
            # Don't care about release actions
            return
        virtual_key = self.__physical_to_virtual(physical_key)

        if self.__timeout > 0 and (self.__lastbutton + self.__timeout < time.time()):
            # Screen timed out, need to wake
            with self.deck:
                self.deck.set_brightness(self.__brightness)
        elif virtual_key >= 0 and virtual_key < len(self.buttons):
            self.__buttons[virtual_key].state = not self.__buttons[virtual_key].state

        self.__lastbutton = time.time()
        self.__update_key_image(virtual_key)


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
            self.screen_rotation = int(screen.get("rotation", 0))

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

            icon_image = icon.get("image", {})

            # Same insane horse shit here as above.
            self.icon_image_on = str(
                icon_image.get(True, icon_image.get("on", "On.png"))
            )
            self.icon_image_off = str(
                icon_image.get(False, icon_image.get("off", "Off.png"))
            )
            self.icon_image_blank = str(icon_image.get("blank", "Blank.png"))


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
            icon_image=(
                config.icon_image_on,
                config.icon_image_off,
                config.icon_image_blank,
            ),
            icon_color=(config.icon_color_on, config.icon_color_off),
            brightness=config.screen_brightness,
            rotation=config.screen_rotation,
            timeout=config.screen_timeout,
        )

        try:

            def buttonfactory(entity: str) -> Button:
                if entity and config.homeassistant_uri and config.homeassistant_token:
                    return HomeAssistantButton(
                        config.homeassistant_uri,
                        config.homeassistant_token,
                        entity,
                    )
                else:
                    return BlankButton()

            driver.add_buttons(
                [buttonfactory(entity) for entity in config.homeassistant_entities]
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
