# MyCashflow cheat sheet

Suomenkielinen, haettava cheat sheet MyCashflow'n teemaoppaan tageille. Sivu rakennetaan Playwright-scrapen tuottamasta JSON-datasta yhdeksi staattiseksi HTML-tiedostoksi, joka tarjoillaan ilmaiseksi GitHub Pagesissa ja päivittyy automaattisesti viikoittain GitHub Actionsilla.

## Hakemistorakenne

```
.github/workflows/update-cheatsheet.yml   # Viikoittainen scrape + build + commit
docs/index.html                           # Julkaistava cheat sheet (GitHub Pages)
docs/.nojekyll                            # Estää Jekyll-prosessoinnin
scripts/scrape_teemaopas.py               # Playwright-scraperi
scripts/build_teemaopas_cheatsheet.py     # JSON -> HTML
scripts/teemaopas-full.json               # Viimeisin onnistunut scrape (commitoidaan repoon)
scripts/requirements-teemaopas.txt        # Python-riippuvuudet
```

## Paikallinen ajo

```bash
cd scripts
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-teemaopas.txt
python -m playwright install chromium

python scrape_teemaopas.py --out teemaopas-full.json --max-pages 1500 --delay 0.25
python build_teemaopas_cheatsheet.py \
  --input teemaopas-full.json \
  --output ../docs/index.html
open ../docs/index.html
```

`build_teemaopas_cheatsheet.py` -lippu `--updated-at` ottaa ISO-8601 -aikaleiman ja
näyttää sen sivulla "Päivitetty viimeksi" -merkkinä. Ilman lippua käytetään JSON-tiedoston
muokkausaikaa.

## Julkaisu ilmaiseksi (GitHub + GitHub Pages)

1. **Luo julkinen GitHub-repo** ja työnnä tämän kansion sisältö sinne.
2. Mene **Settings → Pages**:
   - **Source**: `Deploy from a branch`
   - **Branch**: `main`
   - **Folder**: `/docs`
   - Tallenna. Sivu on muutaman minuutin päästä osoitteessa
     `https://<käyttäjänimi>.github.io/<repo>/`.
3. Mene **Settings → Actions → General** ja varmista, että **Workflow permissions**
   on `Read and write permissions` (jotta automaation push toimii).
4. Käy ajamassa työnkulku kerran manuaalisesti **Actions → Update MyCashflow cheat sheet → Run workflow**, jotta `docs/index.html` syntyy ensimmäistä kertaa.

> Vaihtoehto: jos haluat oman aliasoidun osoitteen, lisää CNAME-tietue `docs/CNAME`-tiedostoon ja kytke se GitHub Pagesin DNS-asetuksiin.

## Automaattinen viikkopäivitys

Tiedosto `.github/workflows/update-cheatsheet.yml` ajaa joka maanantai klo 04:17 UTC (~07:17 Suomen aikaa) seuraavan ketjun:

1. Asentaa Pythonin ja Playwrightin (Chromium).
2. Ajaa scraperin **temp-tiedostoon** (`teemaopas-full.tmp.json`) lipulla
   `--min-tags 120`. Skripti palauttaa exit-koodin 2, jos sivua ei pystytä lukemaan
   tarpeeksi (esim. estetty / merkkaus muuttunut).
3. Validoi temp-JSONin (`tag_page_count >= 120`).
4. Vasta onnistumisen jälkeen siirtää temp-tiedoston päälle `teemaopas-full.json`,
   rakentaa `docs/index.html` ja **commitoi** muutokset takaisin repoon. Pages päivittää
   sivun automaattisesti.
5. Jos jokin vaihe (lataus, validointi, tag-määrä) epäonnistuu, työnkulku
   **ei kirjoita uutta JSONia, ei rakenna uutta HTML:ää eikä päivitä päivämäärää**.
   Edellinen onnistunut versio jää voimaan.

Voit ajaa työnkulun myös käsin **Actions → Update MyCashflow cheat sheet → Run workflow**.

## Tyylien kustomointi (docs/extra.css)

`docs/index.html` on **generoitava artefakti**: viikoittainen workflow korvaa sen
kokonaan, joten siihen tehdyt manuaaliset CSS-muutokset katoavat.

Sen sijaan kustomointi tehdään tiedostossa `docs/extra.css`. Builder linkittää
sen automaattisesti generoidun `<style>`-blokin **jälkeen**, joten sen säännöt
voittavat sisäiset tyylit (sama spesifisyys → myöhempi voittaa).

Workflow ei koskaan kirjoita `docs/extra.css`:n eikä `docs/favicon.png`:n päälle
— se commitoi vain `docs/index.html`, `docs/.nojekyll` ja
`scripts/teemaopas-full.json`.

Esimerkki: muuta brändiväri tummempaan vihreään muokkaamalla GitHubin
web-editorissa `docs/extra.css` ja committoimalla. Pages päivittyy parin minuutin
sisällä, eikä viikkopäivitys koske muutoksiin.

## Aikaleiman logiikka

- HTML:n leima `Päivitetty viimeksi` tulee `--updated-at` -lipusta. CI antaa siihen
  build-hetken UTC-ajan (`date -u`).
- Lokaalissa ajossa ilman lippua leima on `teemaopas-full.json` -tiedoston `mtime`.
- **Jos scrape estyy, leima ei päivity**, koska uutta `--updated-at`-arvoa ei lähetetä
  ja `docs/index.html` jää koskemattomaksi (työnkulku ohittaa build- ja commit-vaiheet).

## Lisenssi ja vastuu

Sivu on epävirallinen, lähdedata on MyCashflow'n teemaoppaasta
(<https://support.mycashflow.com/fi/teemaopas>). Käytä omalla vastuullasi ja
kunnioita lähdesivuston käyttöehtoja.
