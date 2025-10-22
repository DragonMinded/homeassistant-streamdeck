# homeassistant-streamdeck

A simple utility for displaying switches on a Stream Deck. Requires a Home Assistant installation running somewhere, a Long-Lived Access Token issued from your profile on Home Assistant, and a configuration file containing the list of switch entities you want to display. This was not made as a Home Assistant add-on because it is intended to be run on a separate device driving a Stream Deck, possibly mounted to a wall or in a separate room. I recommend using a Raspberry Pi or a Rock Pi S to drive the Stream Deck using this code.

## How To Run This

First, make sure your dependencies are set up:

```
python3 -m pip install -r requirements.txt --upgrade
```

Then, run it like the following:

```
python3 driver.py --config config.yaml
```

Don't forget to edit your config file to customize it for your own setup! If you run into trouble connecting to a Stream Deck (such as getting a DLL error on Windows or a permission error on Linux), please see the streamdeck library setup instructions at https://python-elgato-streamdeck.readthedocs.io/en/stable/pages/backend_libusb_hidapi.html

## Config File Documentation

The `config.yaml` sample configuration can be edited or copied to make a configuration file that you are happy with. It has a variety of options, some of which you must configure and some of which you can tweak only if you want to mess with options.

### Font Options

The font face is the actual true type font that should be used for rendering individual entity labels. It must exist in the `Assets/` folder. A default has been provided for you, but you can find your own font and place it in the directory if you want. The font size is the point size that the entity labels will be rendered in. You can modify this to make the labels bigger or smaller. The font rows is the minimum number of rows you want the labels for buttons to take up. It's defaulted to 1 which will align text to the bottom of the button, but you can adjust the minimum number of rows if you want to align all text across buttons and some of your labels take up more than one line.

### Screen Options

The brightness is a number between 0 and 100 that specifies the percent brightness that the Stream Deck should be set at. The timeout is a number in seconds that specifies how long to wait before blanking the screen. If you do not wish for this behavior, set the timeout to 0. Otherwise, the Stream Deck will go blank after the listed number of seconds. The rotation is the degrees clockwise that you have rotated the Stream Deck if you are mounting it in a non-standard way. You can specify 0, 90, 180 or 270, as well as -90, -180 and -270 to specify a counter-clockwise rotation. This software will always refer to the top left button from your perspective as the first button and lay out buttons left to right then top to bottom.

### Icon Options

The icon images are the actual pictures that get drawn for an entity that is on, off or for a button that doesn't have an entity associated with it. You can customize this by specifying your own PNG images to use if you like. They must live inside the `Assets/` folder, much like the font. They will be scaled for you. The icon colors are the colors that will be used to tint the on and off images as well as the blank image. By default, the on and off images use pure white and HTML colors are specified in order to tint them.  Note that if you choose instead to use full color images, you should set both the on and off color to `"#FFFFFF"` in order to stop tinting the images.

If an MDI section is specified in the configuration file, then MDI icons as specified in your entity configuration on your Home Assistant instance will be used instead of icons in your assets folder. If you want to use a custom set of icons for the on and off states, delete the MDI section in your configuration. Otherwise, the same icons that appear on your Home Assistant instance will be used on your Stream Deck as well. The icons will be rendered with the same on and off colors that custom PNG images will using the same HTML colors specified in the config file.

### Home Assistant Options

The URL should be the access URL that you type into a browser in order to connect to your Home Assistant installation. It should start with `http://` or `https://` but you can choose to use the internal or external URL as long as the device running this software can connect to it through the local network. If you place the device on a separate network, then you should use the public URL. The token is a Long-Lived Access Token that you have generated to authorize this software to connect to your Home Assistant installation. You can generate one by going to your profile in a web browser and scrolling to the bottom. Finally, the entities are a list of entity IDs in Home Assistant that you want to display and control on the Stream Deck. You can find these entity IDs in the Settings->Devices and Services->Entities panel under the "Entity ID" column. Currently this only supports switch entities and blank spacers. If you want to add a spacer to a Stream Deck button you can add a blank line to the list of entities.

If you wish to use a graphic with a particular spacer instead of the configured blank image, you can do so with a special syntax. Assuming you have MDI icons configured properly, you can select a particular MDI icon by adding an entity prefixed with "mdi:". For instance, to show the Xbox logo in a blank spot, add an entity named `"mdi:microsoft-xbox"` to your entities list. Similarly, if you wish to use a graphic file, you can add an entity prefixed with "image:". For instance, to show a graphic called "Test.png" inside the `Assets/` directory, add an entity named `"image:Test.png"` to your entities list. Note that these images will be colored using the blank color as specified in the icon option section.

Optionally, a monitoring server can be opened that will allow you to periodically check that your device is up and running properly. You can use this if you want to monitor a Stream Deck being driven off of a flaky wifi connection. If you want this, set enabled to "true" under the Home Assistant monitoring section. If you wish to change the port as well, you can do so by editing the port. Note that the port must be between 1 and 65535. If you are on a unix system then ports below 1024 require root access to use.

### Example Config File

```
homeassistant:
  url: https://my.homeassistant.url.com/
  token: really-long-token-string-i-copied-from-home-assistant
  entities:
    - switch.kitchen_1
    - switch.kitchen_2
    - switch.living_room
    - switch.dining_room
    - switch.den
    - switch.master_bath
    - switch.master_bed
    -
    - switch.guest_room
    - switch.office
    - switch.back_porch
    - switch.front_porch
    - switch.front_deck
    - switch.side_yard
    -
    -
    - switch.garage
font:
  face: DejaVuSans.ttf
  size: 12
  rows: 1
icon:
  image:
    on: On.png
    off: Off.png
    blank: Blank.png
  color:
    on: "#FDD835"
    off: "#44739E"
    blank: "#FFFFFF"
screen:
  brightness: 50
  rotation: 0
  timeout: 60
```

## Quirks

Some Stream Decks running older firmwares will not fully blank the screen when the brightness is set to zero. There's a workaround for this in software, but you will still see a faint glow from the blanked buttons. If this is undesirable then make sure your firmware is at least at 1.01.000 (the current latest firmware for the Stream Deck XL as of this writing). The firmware seems to be upgradeable only with the official software at this point.
