# homeassistant-streamdeck

A simple utility for displaying switches on a StreamDeck. Requires a Home Assistant installation running somewhere, a Long-Lived Access Token issued from your profile on Home Assistant, and a configuration file containing the list of switch entities you want to display. This was not made as a Home Assistant add-on because it is intended to be run on a separate device driving a StreamDeck, possibly mounted to a wall or in a separate room. I recommend using a Raspberry Pi or a Rock Pi S to drive the StreamDeck using this code.

## How To Run This

First, make sure your dependencies are set up:

```
python3 -m pip install -r requirements.txt --upgrade
```

Then, run it like the following:

```
python3 driver.py --config config.yaml
```

Don't forget to edit your config file to customize it for your own setup! If you run into trouble connecting to a StreamDeck (such as getting a DLL error on Windows or a permission error on Linux), please see the streamdeck library setup instructions at https://python-elgato-streamdeck.readthedocs.io/en/stable/pages/backend_libusb_hidapi.html

## Config File Documentation

The `config.yaml` sample configuration can be edited or copied to make a configuration file that you are happy with. It has a variety of options, some of which you must configure and some of which you can tweak only if you want to mess with options.

### Font Options

The font face is the actual true type font that should be used for rendering individual entity labels. It must exist in the `Assets/` folder. A default has been provided for you, but you can find your own font and place it in the directory if you want. The font size is the point size that the entity labels will be rendered in. You can modify this to make the labels bigger or smaller.

### Screen Options

The brightness is a number between 0 and 100 that specifies the percent brightness that the StreamDeck should be set at. The timeout is a number in seconds that specifies how long to wait before blanking the screen. If you do not wish for this behavior, set the timeout to 0. Otherwise, the StreamDeck will go blank after the listed number of seconds.

### Icon Options

The icon images are the actual pictures that get drawn for an entity that is on, off or for a button that doesn't have an entity associated with it. You can customize this by specifying your own PNG images to use if you like. They must live inside the `Assets/` folder, much like the font. They will be scaled for you. The icon colors are the colors that will be used to tint the on and off images. By default, the on and off images use pure white and HTML colors are specified in order to tint them.  Note that if you choose instead to use full color images, you should set both the on and off color to `"#FFFFFF"` in order to stop tinting the images.

### Home Assistant Options

The URL should be the access URL that you type into a browser in order to connect to your Home Assistant installation. It should start with `http://` or `https://` but you can choose to use the internal or external URL as long as the device running this software can connect to it through the local network. If you place the device on a separate network, then you should use the public URL. The token is a Long-Lived Access Token that you have generated to authorize this software to connect to your Home Assistant installation. You can generate one by going to your profile in a web browser and scrolling to the bottom. Finally, the entities are a list of entity IDs in Home Assistant that you want to display and control on the StreamDeck. You can find these entity IDs in the Settings->Devices and Services->Entities panel under the "Entity ID" column. Currently this only supports switch entities. If you want to add a spacer to a StreamDeck button you can add a blank line to the list of entities.

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
icon:
  image:
    on: On.png
    off: Off.png
    blank: Blank.png
  color:
    on: "#FDD835"
    off: "#44739E"
screen:
  brightness: 50
  timeout: 60
```