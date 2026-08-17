# Kagi for Wox

Drive [Kagi](https://kagi.com) from the Wox launcher: web search with live
autocomplete, every Kagi search vertical, and the standalone products
(Assistant, Translate, Universal Summarizer, Small Web, Kagi News).

Autocomplete is free and needs no account. Everything else opens Kagi in your
browser, so a plain install costs nothing and sends nothing but your keystrokes
to Kagi's public suggestion endpoint. The paid Kagi APIs are supported too, but
they are opt in — see [Inline answers](#inline-answers-paid).

## Install

```
wpm install Kagi
```

## Use

Type the trigger keyword (`kagi` or `k`), then a service keyword, then your
query:

```
kagi red pandas          → web search, with autocomplete suggestions
kagi img red pandas      → image search
kagi tr guten tag        → Kagi Translate
kagi sum https://…       → Universal Summarizer
kagi                     → list every enabled service
```

A query with no service keyword goes to web search.

### Services and default keywords

| Keyword | Service              | What it does                                     |
| ------- | -------------------- | ------------------------------------------------ |
| *none*  | Web Search           | The fallback for any unprefixed query            |
| `img`   | Image Search         | Kagi Images                                      |
| `vid`   | Video Search         | Kagi Videos                                      |
| `news`  | News Search          | Kagi News results                                |
| `pod`   | Podcast Search       | Kagi Podcasts                                    |
| `map`   | Maps                 | Kagi Maps                                        |
| `ask`   | Assistant            | Kagi Assistant                                   |
| `gpt`   | Quick Answer         | FastGPT, a cited one shot answer                 |
| `sum`   | Universal Summarizer | Summarize a page, video or document              |
| `tr`    | Translate            | Kagi Translate                                   |
| `proof` | Proofread            | Grammar and style corrections                    |
| `dict`  | Dictionary           | Word lookup                                      |
| `small` | Small Web            | Independent, non commercial sites                |
| `kite`  | Kagi News            | The Kite daily briefing                          |

Every keyword is configurable, and every service can be turned off.

### Actions

Each result carries more than one action — open the Wox action panel to reach
them.

- **Open in browser** (default)
- **Copy link**
- **Open in Image Search / Video Search / …** — the same term in another
  vertical, listed for whichever verticals you have enabled
- **Summarize this page** — on inline API results
- **Put in search box** — on a suggestion, to keep typing from there

### Translating into another language

Translate uses the languages set in the plugin settings. Override the target
for a single query with a trailing `> code`:

```
kagi tr guten tag > fr
```

## Settings

Open Wox settings, then the plugin's own settings tab.

### Autocomplete

| Setting                | Default | Notes                                             |
| ---------------------- | ------- | ------------------------------------------------- |
| Show suggestions       | on      | Uses `kagisuggest.com`, free, no account needed    |
| Maximum suggestions    | 6       | 0 turns the list off without disabling the lookup  |
| Network timeout        | 6 s     | Applies to every Kagi request                      |

### Kagi API

Leave the API key empty to use the plugin purely as a launcher. Create a key at
[kagi.com/settings?p=api](https://kagi.com/settings?p=api) to unlock inline
answers.

### Inline answers (paid)

Kagi's APIs are billed per call against your account balance, so each one has
its own switch and all three ship **off**:

| Setting                        | What it calls                     | Billing         |
| ------------------------------ | --------------------------------- | --------------- |
| Show results inline            | Search and Enrichment APIs        | Per search      |
| Answer Quick Answer inline     | FastGPT API                       | Per query       |
| Summarize inline               | Universal Summarizer API          | Per token       |

With a switch on, the plugin calls that API on every matching query. Responses
are cached for 15 minutes so repeated keystrokes are not billed twice. The
result list always keeps the plain "open in browser" entry, so a failed or
unauthorized API call never leaves you stuck.

### Services and keywords

Each service has a checkbox and a keyword box.

- Clearing a keyword leaves the service reachable only from the `kagi` service
  list.
- Two services cannot share a keyword. If they do, the second one loses its
  keyword and the plugin says so in the result list.
- Web Search has no keyword by default because it is what an unprefixed query
  falls back to. Give it one if you want an explicit `kagi web …`.

Keywords are registered with Wox as query commands whenever the settings
change, so Wox autocompletes them for you.

## Development

```
make install   # sync dependencies
make test      # run the unit tests
make lint      # ruff + mypy
make package   # build wox.plugin.kagi.wox
```

`plugin.json` is generated from the service catalog in `src/services.py`;
`tests/test_manifest.py` fails if the two drift apart.

Layout:

| File                 | Contents                                            |
| -------------------- | --------------------------------------------------- |
| `src/main.py`        | Query dispatch, result and action building          |
| `src/services.py`    | The service catalog and URL builder                 |
| `src/settings.py`    | Reading and validating settings                     |
| `src/kagi_client.py` | The HTTP client, standard library only              |
| `src/text.py`        | Snippet cleaning and query parsing helpers          |

## License

See [LICENSE](LICENSE).
