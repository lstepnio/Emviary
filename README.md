# Emviary

Emviary is an e-paper picture frame built as a gift. It shows Colorado birds,
wildlife, and artwork for special occasions on a reTerminal E1002.

![The finished Emviary frame](src/emviary/showcase_assets/08-dark-studio.webp)

[Website](https://emviary.majjix.com/) · [User guide](https://emviary.majjix.com/guide) ·
[Owner management](https://emviary.majjix.com/manage) ·
[Frame gallery](docs/FRAME_GALLERY.md) ·
[Firmware](https://github.com/lstepnio/Emviary-firmware)

The homepage shows the last picture sent to the frame selected for sharing.
It can include family artwork and personalized Special Days. The product
gallery uses AI-assisted renderings based on photos of the finished frame.

## Battery life

Early measurements suggest **more than a year between charges**.
The picture stays visible when the battery runs out. With power, the frame can
keep cycling through saved pictures even if Wi-Fi drops.
[Battery results and how we estimated them](docs/BATTERY_RESULTS.md)

## How it works

A small Python service picks the artwork, adds local weather when available,
and prepares the picture before the frame wakes. The frame downloads it,
refreshes the screen, and goes back to sleep.

Regional bird reports help choose what appears. The collection includes
historical illustrations, original birds and wildlife, and pet portraits.
The frame runs without an AI service or subscription.

## Build effort and AI usage

Emviary went from the October 7 design decision to the November 26, 2026 rollout
in **seven weeks**. Local logs recorded **46 hours of Codex activity across 21
days** and **298 saved image outputs**, including drafts and variations. The
build also involved hands-on assembly and testing, for which there is no complete
time record. [Project timeline](DEPLOYMENT.md#archived-october-7-deployment-specification)

The recorded AI usage is worth **about $325** at published rates, with an estimated
range of **$300–$355**. That includes about $285 for Codex model usage and $15–$70
for image generation and edits. Actual charges depend on subscription coverage
and any additional credits.
[OpenAI rate card](https://help.openai.com/en/articles/20001415-chatgpt-rate-card-enterprise-token-based-pricing)

A comparable build **without AI**, starting with the same hardware and
open-source firmware, is estimated at **1,100–1,950 person-hours** or **4–6 months
for a small team**. At assumed U.S. contractor rates of $100–$145 per hour, that
works out to roughly **$110,000–$280,000 in labor** for firmware, web and backend
development, device testing, and comparable custom artwork.

## Everyday controls

| Control | What it does |
| --- | --- |
| Tap left white | Go back one picture. |
| Tap right white | Go to the next picture or open the gift if the welcome is showing. |
| Hold left white for 5 seconds | Show the frame’s status. |
| Press green | Wake the frame for Wi-Fi and local controls, or leave the status screen. On USB power, it also checks for new pictures. |
| Plug in USB-C | Power and charge the frame. |

**Opening the gift.** Once the frame is ready to wrap, the welcome stays put
through scheduled updates and charging. Flip the power switch on to reveal the
first picture, even without Wi-Fi.

**Changing pictures.** On battery, tap right white to go forward. Press once
and give the screen about 30 seconds to finish. Flashing during a refresh is normal.

If Wi-Fi drops, the frame can keep rotating saved pictures on its usual schedule.
Those pictures skip special occasions and old forecasts. A small battery icon
appears on the next regular refresh at 25% or below and clears at 28% or when
external power is detected.

## Manage the frame

Open [Owner management](https://emviary.majjix.com/manage) to change the artwork
and schedule, set up special days, check the battery, or reconnect the frame to
Wi-Fi. Sign in with your owner account or use [trusted home access](deployment/TRUSTED_NETWORK_ACCESS.md)
if you've enabled it.

## Set up a gift

Use firmware that supports opening the gift at power-on. That feature was
introduced in v0.8.16. Keep the frame on and connected to Wi-Fi during setup.

1. Open **Manage → Appearance → Gift welcome**. Write the welcome message,
   choose the first picture, and click **Prepare gift preview**.
2. Review both pictures and click **Show welcome on frame**. Press the
   **right white button** once to load them onto the frame.
3. Check that the welcome is actually on the screen. In **Gift welcome**, tick
   **I can see the welcome on the frame** and click **Ready to wrap**.
4. Wait for **Ready to wrap** to appear as the frame's status. If the frame went
   to sleep, press green once and wait for it to finish. Unplug USB-C, switch
   the frame off, and wrap it. Leave it off until the recipient opens the gift.

When the recipient flips the power switch on, the first picture appears
automatically, even without Wi-Fi.
[Gift setup and troubleshooting](RUNBOOK.md#gift-welcome)

## Local development

Clone the repo with its firmware submodule, install the dependencies, and
start the service with a local test frame.

```sh
git clone --recurse-submodules https://github.com/lstepnio/Emviary.git
cd Emviary
uv sync --locked
npm ci --ignore-scripts --prefix converter
npm run install --prefix converter/node_modules/canvas
uv run emviary add-frame local-e1002 --token-file .state/provisioning/local-e1002.token
uv run emviary prepare local-e1002 --offline
uv run emviary serve
```

The service uses the [example configuration](deployment/site.example.json)
by default. For a local owner login, set `EMVIARY_SECRET_DIR` to a private,
writable directory and run the command below. See the [runbook](RUNBOOK.md)
for configuration and recovery.

```sh
uv run emviary init-owner --password-file .state/provisioning/owner-login.txt
```

Keep passwords, tokens, provider keys, and original family and pet photos private.

Run the service and browser recovery checks before sending changes.

```sh
uv run ruff check src tests tools
uv run ruff format --check src tests tools
uv run pytest -q
npm ci --prefix web-recovery
npm test --prefix web-recovery
npm run build --prefix web-recovery
```

See [deployment](DEPLOYMENT.md) for release and backup steps, the
[project structure](PROJECT_STRUCTURE.md) for where things live, and the
[research index](research/README.md) for design notes and test results.

## Artwork and attribution

The service code is MIT licensed. Check the catalog for each artwork's license
before reusing it. Fonts use the SIL Open Font License.
[Artwork catalog](art/catalog.json) ·
[Fugleramme credits](art/FUGLERAMME-ATTRIBUTION.md) ·
[Colorado source credits](art/COLORADO-ATTRIBUTION.md) ·
[Original birds](art/provenance/ai-color-cutouts/README.md) ·
[Wildlife](art/wildlife/README.md) ·
[Special occasions](art/occasions/README.md)

Emviary was previously called eInkArtifact.
