# mix-parlay-filter

Football odds filter using FotMob for fixture, H2H, and team-form data.

## Run

Install the packages in `requirements.txt`, then run:

```sh
python main.py
```

The FotMob data endpoints used here are unofficial and are not a supported
public API. FotMob's API page says automated or regular systematic use is not
permitted. The client caches successful responses, spaces requests, and stops
on HTTP 403/429; these measures reduce repeat traffic but do not make recurring
automated use permitted or guarantee access. Do not use proxies or IP rotation
to bypass a restriction. No FotMob API key is required.

The expected-value calculation remains heuristic and has not been validated
against historical results. A qualifying pick is not a guarantee of an outcome.