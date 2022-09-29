A simple utility for displaying switches on a StreamDeck. Requires a Home Assistant installation running somewhere, a Long-Lived Access Token issued from your profile on Home Assistant, and a configuration file containing the list of switch entities you want to display. This was not made as a Home Assistant add-on because it is intended to be run on a separate device driving a StreamDeck, possibly mounted to a wall or in a room. I recommend using a Raspberry Pi or a Rock Pi S to drive the StreamDeck using this code.

First, make sure your dependencies are set up:

```
python3 -m pip install -r requirements.txt --upgrade
```

Then, run it like the following:

```
python3 driver.py --config config.yaml
```

Don't forget to edit your config file to customize it for your own setup!
