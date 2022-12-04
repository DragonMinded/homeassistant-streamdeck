#!/usr/bin/env python3
import argparse
import os
import requests
import threading
import time
import yaml
from multiprocessing import Process
from typing import Any, Dict, List, Optional, Sequence, Tuple

import tinycss2  # type: ignore
from PIL import Image, ImageDraw, ImageFont, ImageChops  # type: ignore
from StreamDeck.DeviceManager import DeviceManager  # type: ignore
from StreamDeck.ImageHelpers import PILHelper  # type: ignore
from StreamDeck.Transport.Transport import TransportError  # type: ignore


# Folder location of image assets used by this example.
ASSETS_PATH = os.path.join(os.path.dirname(__file__), "Assets")


# Since the library is untyped.
StreamDeck = Any
StreamDeckImage = Any


class IconColor:
    def __init__(self, *, on: str, off: str, blank: str) -> None:
        self.on = on
        self.off = off
        self.blank = blank


class IconImage:
    def __init__(self, *, on: str, off: str, blank: str) -> None:
        self.on = on
        self.off = off
        self.blank = blank


class IconMDI:
    def __init__(self, *, css: Optional[str], face: Optional[str]) -> None:
        self.css = css
        self.face = face


class KeyStyle:
    def __init__(self, *, icon: str, label: Optional[str], color: str) -> None:
        self.icon = icon
        self.label = label
        self.color = color


class Button:
    def __init__(self, label: str, icon: Optional[str]) -> None:
        self.label: str = label
        self.icon: Optional[str] = icon

    @property
    def state(self) -> Optional[bool]:
        return None

    @state.setter
    def state(self, newstate: bool) -> None:
        raise NotImplementedError("Not implemented!")


class BlankButton(Button):
    def __init__(self, icon: Optional[str] = None) -> None:
        super().__init__("", icon)

    @property
    def state(self) -> Optional[bool]:
        return False

    @state.setter
    def state(self, newstate: bool) -> None:
        pass


class HomeAssistantButton(Button):
    def __init__(self, uri: str, token: str, entity: str) -> None:
        super().__init__(entity, None)
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
        try:
            response = requests.get(url, headers=headers, timeout=3.0)
            response.raise_for_status()

            data = response.json()
            if data.get("entity_id", None) != self.entity:
                return None

            icon = data.get("attributes", {}).get("icon", None) or ""
            if icon[:4].lower() == "mdi:":
                self.icon = icon.lower()
            self.label = data.get("attributes", {}).get("friendly_name", self.label)
            return bool(data.get("state", "off").lower() == "on")
        except Exception as e:
            print(f"Failed to fetch {self.entity} state!\n{e}")
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
        try:
            requests.post(url, headers=headers, json=request, timeout=3.0)
        except Exception as e:
            print(f"Failed to update {self.entity} state!\n{e}")


class StreamDeckDriver:
    def __init__(
        self,
        deck: StreamDeck,
        font: str = "DejaVuSans.ttf",
        icon_mdi: IconMDI = IconMDI(css=None, face=None),
        icon_image: IconImage = IconImage(
            on="On.png", off="Off.png", blank="Blank.png"
        ),
        icon_color: IconColor = IconColor(on="#FFFFFF", off="#777777", blank="#555555"),
        fontsize: int = 14,
        brightness: int = 30,
        rotation: int = 0,
        timeout: int = 60,
    ) -> None:
        # We want to enable or disable quirks based on the firmware revision of the
        # deck in question as well as the model number. This is sketchy business because
        # we don't have a complete list of values, so we instead do an opt-in style instead
        # of a version number comparison style.
        if deck.deck_type() == "Stream Deck XL":
            # Brightness quirk is based on the firmware revision. The latest firmware
            # doesn't have this bug, but others might and I don't know what revisions exist.
            self.__brightness_quirk = {
                "1.01.000": False,
                "1.00.010": True,
                "1.00.006": False,
            }.get(deck.get_firmware_version(), True)
        else:
            # No known quirks modes for these other deck types right now.
            self.__brightness_quirk = False

        self.deck: StreamDeck = deck
        self.__buttons: List[Button] = []
        self.__states: Dict[int, Optional[bool]] = {}
        self.__images: Dict[str, StreamDeckImage] = {}
        self.__height: int = fontsize
        self.__font: ImageFont.ImageFont = ImageFont.truetype(
            os.path.join(ASSETS_PATH, font), self.__height
        )
        self.__icon_colors = icon_color
        self.__icon_images = icon_image
        self.__closed = False
        self.__timeout = timeout
        self.__blanked = False
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

        # Parse and set up MDI if provided
        self.__mdi_mapping: Dict[str, str] = {}
        self.__mdi_font: Optional[ImageFont.ImageFont] = None

        if icon_mdi.css and icon_mdi.face:
            actual_css = os.path.join(ASSETS_PATH, icon_mdi.css)
            mapping: Dict[str, str] = {}

            with open(actual_css, "rb") as bfp:
                data = bfp.read()
            rules, _ = tinycss2.parse_stylesheet_bytes(data)
            for rule in rules:
                if not isinstance(rule, tinycss2.ast.QualifiedRule):
                    continue

                # Should be in the form of ".mdi-xxx::before"
                if len(rule.prelude) < 2:
                    continue

                if not isinstance(rule.prelude[0], tinycss2.ast.LiteralToken):
                    continue
                if rule.prelude[0].value != ".":
                    continue

                if not isinstance(rule.prelude[1], tinycss2.ast.IdentToken):
                    continue
                token = rule.prelude[1].lower_value
                if token[:4] != "mdi-":
                    continue

                content = [
                    x.value
                    for x in rule.content
                    if isinstance(
                        x,
                        (
                            tinycss2.ast.IdentToken,
                            tinycss2.ast.LiteralToken,
                            tinycss2.ast.StringToken,
                        ),
                    )
                ]

                # Should be in the form of "content: 'unicode';"
                if len(content) != 4:
                    continue
                if content[0] != "content" or content[1] != ":" or content[3] != ";":
                    continue

                # We have our unicode mapping.
                mapping[f"mdi:{token[4:]}"] = content[2]

            self.__mdi_mapping = mapping
            self.__mdi_font = ImageFont.ImageFont = ImageFont.truetype(
                os.path.join(ASSETS_PATH, icon_mdi.face), 64
            )

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
        # When we blank the screen we want it to be fast, since you can "see"
        # the redraw times if we refresh every state along the way.
        cache_only = False

        if self.__timeout > 0 and ((self.__lastbutton + self.__timeout) < time.time()):
            # Screen timed out, need to turn off backlight and also blank images
            # in case this is a model that still shows some graphics when set to
            # 0 brightness.
            cache_only = self.__brightness_quirk
            with self.deck:
                self.deck.set_brightness(0)
                self.__blanked = True

        for i in range(self.deck.key_count()):
            self.__update_key_image(i, cached_only=cache_only)

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

    def __get_font_params(
        self, font: ImageFont.ImageFont, line: str
    ) -> Tuple[int, int]:
        left, top, right, bottom = font.getbbox(line)
        return (abs(right - left), abs(bottom - top))

    def __get_wrapped_text(
        self, font: ImageFont.ImageFont, label_text: str, line_length: int
    ) -> List[Tuple[str, int, int]]:
        lines = [""]
        for word in label_text.split():
            oldline = lines[-1].strip()
            line = f"{lines[-1]} {word}".strip()

            if font.getlength(line) <= line_length:
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

        return [(ln, *self.__get_font_params(font, ln)) for ln in lines if ln]

    def __render_key_image(
        self, icon_filename: str, icon_color: str, label_text: Optional[str]
    ) -> StreamDeckImage:
        cache_key = f"{icon_filename}-{icon_color}-{label_text}-{self.__rotation}"

        if cache_key not in self.__images:
            # First, draw the icon.
            if icon_filename[:4] == "mdi:":
                icon = Image.new("RGB", (64, 64))
                image = PILHelper.create_scaled_image(
                    self.deck,
                    icon,
                    margins=[0, 0, 20 if label_text is not None else 0, 0],
                )

                # We control this, so we don't care about anything other than
                # the first line.
                text = self.__mdi_mapping[icon_filename]
                widths = self.__get_wrapped_text(self.__mdi_font, text, image.width)

                mdi_draw = ImageDraw.Draw(image)
                mdi_draw.text(
                    (
                        (image.width - widths[0][1]) / 2,
                        (image.height - widths[0][2]) / 2 if label_text is None else 0,
                    ),
                    text=text,
                    anchor="lt",
                    font=self.__mdi_font,
                    fill=icon_color,
                )
            else:
                icon = Image.open(icon_filename)
                iconimage = PILHelper.create_scaled_image(
                    self.deck,
                    icon,
                    margins=[0, 0, 20 if label_text is not None else 0, 0],
                )
                colorimage = Image.new("RGB", iconimage.size, icon_color)
                image = ImageChops.multiply(iconimage, colorimage)

            draw = ImageDraw.Draw(image)

            if label_text is not None:
                lines = self.__get_wrapped_text(self.__font, label_text, image.width)
                numlines = len(lines)
                if numlines < 2:
                    numlines = 2

                for lno, (line, width, _) in enumerate(lines):
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

            self.__images[cache_key] = PILHelper.to_native_format(self.deck, image)

        return self.__images[cache_key]

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

    def __update_key_image(
        self, virtual_key: int, *, cached_only: bool = False
    ) -> None:
        # Figure out if this is a registered key or a blank key.
        valid_key = not (
            virtual_key < 0
            or virtual_key >= len(self.__buttons)
            or isinstance(self.__buttons[virtual_key], BlankButton)
        )

        if self.__blanked and self.__brightness_quirk:
            # Special case for when we should display nothing, for cases where
            # setting brightness to 0 does not actually fully blank the screen.
            # We rely on blending with all black to set all pixels to zero. Kinda
            # a hack but it works.
            key_style = KeyStyle(
                icon=os.path.join(ASSETS_PATH, self.__icon_images.blank),
                label=None,
                color="#000000",
            )

            # We also want to keep a running tally of the cached state so if something
            # changes while we're blanked we display it instantly on wake.
            if valid_key and not cached_only:
                self.__states[virtual_key] = self.__buttons[virtual_key].state
        elif not valid_key:
            # Blank buttons can still have images associated with them.
            try:
                actual_button = self.__buttons[virtual_key]
                if (
                    self.__mdi_font is not None
                    and actual_button.icon is not None
                    and actual_button.icon in self.__mdi_mapping
                ):
                    button_image = actual_button.icon
                elif (
                    actual_button.icon is not None
                    and actual_button.icon[:6].lower() == "image:"
                ):
                    button_image = os.path.join(ASSETS_PATH, actual_button.icon[6:])
                else:
                    button_image = None

            except (KeyError, IndexError):
                button_image = None

            key_style = KeyStyle(
                icon=button_image
                or os.path.join(ASSETS_PATH, self.__icon_images.blank),
                label=None,
                color=self.__icon_colors.blank,
            )
        else:
            actual_button = self.__buttons[virtual_key]
            if cached_only:
                state = self.__states.get(virtual_key, None)
            else:
                self.__states[virtual_key] = state = actual_button.state

            if (
                self.__mdi_font is not None
                and actual_button.icon is not None
                and actual_button.icon in self.__mdi_mapping
            ):
                # MDI icon
                icon = actual_button.icon
            else:
                # Normal icon path
                icon = os.path.join(
                    ASSETS_PATH,
                    self.__icon_images.on if state else self.__icon_images.off,
                )

            key_style = KeyStyle(
                icon=icon,
                label=actual_button.label,
                color=self.__icon_colors.on if state else self.__icon_colors.off,
            )

        image = self.__render_key_image(
            key_style.icon, key_style.color, key_style.label
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
                self.__blanked = False

            self.__lastbutton = time.time()
            if self.__brightness_quirk:
                # Need to redraw all buttons now that we woke up since we manually
                # blanked the screen as well as set the brightness down. Use the last
                # cached value so that we can display instantly.
                for i in range(self.deck.key_count()):
                    self.__update_key_image(i, cached_only=True)

            return

        if virtual_key >= 0 and virtual_key < len(self.buttons):
            # Update the state given that this is a valid button press. This will
            # involve making a callback inside the button class possibly to change
            # a remote state.
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

            # If present, read the monitoring port argument to put a simple HTTP
            # monitoring page up.
            monitoring = hass.get("monitoring", {})
            enabled = bool(monitoring.get("enabled", False))
            if enabled:
                port = int(monitoring.get("port", 8080))
            else:
                port = None
            self.homeassistant_monitoring_port: Optional[int] = port

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
            self.icon_color_blank = str(icon_color.get("blank", "#555555"))

            icon_image = icon.get("image", {})

            # Same insane horse shit here as above.
            self.icon_image_on = str(
                icon_image.get(True, icon_image.get("on", "On.png"))
            )
            self.icon_image_off = str(
                icon_image.get(False, icon_image.get("off", "Off.png"))
            )
            self.icon_image_blank = str(icon_image.get("blank", "Blank.png"))

            icon_mdi = icon.get("mdi", {})
            self.icon_mdi_css: Optional[str] = icon_mdi.get("css", None)
            self.icon_mdi_face: Optional[str] = icon_mdi.get("face", None)


def monitoring_thread(port: int, decktype: str, serial: str, version: str) -> None:
    # Conditional import to stop the driver itself from needing a flask
    # dependency if you only want to import and use StreamDeckDriver in
    # your own code.
    import json
    from flask import Flask, Response

    app = Flask("monitoring thread")

    @app.route("/")
    def monitor() -> Response:
        return Response(
            response=json.dumps(
                {
                    "type": decktype,
                    "serial": serial,
                    "version": version,
                }
            ),
            status=200,
            mimetype="application/json",
        )

    try:
        print(f"Listening on port {port} for monitoring HTTP requests.")

        # Kinda stupid that we can't disable this. I don't care that this is non-production,
        # its literally a monitoring port for a dang wall-mounted local interface.
        import sys

        f = open(os.devnull, "w")
        sys.stdout = f
        sys.stderr = f

        app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
    except KeyboardInterrupt:
        # Silently exit without spewing
        pass


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
    proc: Optional[Process] = None

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
            icon_mdi=IconMDI(
                css=config.icon_mdi_css,
                face=config.icon_mdi_face,
            ),
            icon_image=IconImage(
                on=config.icon_image_on,
                off=config.icon_image_off,
                blank=config.icon_image_blank,
            ),
            icon_color=IconColor(
                on=config.icon_color_on,
                off=config.icon_color_off,
                blank=config.icon_color_blank,
            ),
            brightness=config.screen_brightness,
            rotation=config.screen_rotation,
            timeout=config.screen_timeout,
        )

        if config.homeassistant_monitoring_port is not None:
            proc = Process(
                target=monitoring_thread,
                args=(
                    config.homeassistant_monitoring_port,
                    found_deck.deck_type(),
                    found_deck.get_serial_number(),
                    found_deck.get_firmware_version(),
                ),
            )
            proc.start()

        try:

            def buttonfactory(entity: Optional[str]) -> Button:
                if entity and (
                    entity[:4].lower() == "mdi:" or entity[:6].lower() == "image:"
                ):
                    return BlankButton(icon=entity)
                elif entity and config.homeassistant_uri and config.homeassistant_token:
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
        finally:
            # Kill monitor thread now that we're out.
            if proc:
                proc.terminate()

        # We only support driving the first found stream deck.
        break

    # Wait until all application threads have terminated (all deck handles are closed).
    for t in threading.enumerate():
        try:
            t.join()
        except RuntimeError:
            pass
