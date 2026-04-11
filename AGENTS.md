# AGENTS.md

Referencyjny dokument dla LLM pracujacych na repozytorium GUPB.
Cel: szybkie zrozumienie architektury kodu, mechanik gry i kontraktu botow.

## 1. Co to za projekt

GUPB (Gra Udajaca Prawdziwe Battle-Royale) to uproszczona 2D gra turowa uzywana na zajeciach z uczenia maszynowego.
Repo zawiera silnik gry, renderer, konfiguracje rozgrywek i boty.

## 2. Szybki start

Uruchom z katalogu glownnego:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m gupb
```

Domyslnie uruchamiany jest config `gupb/default_config.py`.

## 3. Struktura repo

- `README.md`: podstawowe informacje.
- `requirements.txt`: zaleznosci.
- `profiling.md`: opis profilowania.
- `resources/`
  - `arenas/*.gupb`: mapy.
  - `images/`: sprite'y.
  - `fonts/`: font.
- `results/`: logi.
- `gupb/`: kod aplikacji.

Najwazniejsze moduly w `gupb/`:

- `__init__.py`: event loop i env vars.
- `__main__.py`: CLI, ladowanie configu, inquiry, logowanie.
- `runner.py`: uruchamianie serii gier i ranking.
- `model/`: cala logika gry.
- `view/render.py`: wizualizacja Pygame.
- `controller/`: boty i sterowanie reczne.
- `scripts/`: generator map i parser wynikow.

## 4. Przeplyw wykonania

1. `python -m gupb` uruchamia `gupb.__main__.main`.
2. Ladowany jest `CONFIGURATION` z pliku config.
3. Tworzony jest `Runner(config)`.
4. `Runner.run()` odpala `runs_no` gier.
5. Kazda gra to `Game` (state machine).
6. Na koncu `Runner.print_scores()` drukuje wyniki.

## 5. Cykl gry (Game state machine)

Stany:

- `actions_done` (value `9`)
- `instants_triggered` (value `1`)

Cykl:

1. Gdy kolejka akcji jest pusta:
   - czyszczenie martwych championow,
   - nowa kolejka akcji zywych,
   - nowy epizod,
   - ewentualnie zwiekszenie mgly.
2. Gdy kolejka nie jest pusta:
   - jeden champion wykonuje akcje.
3. W `instants_triggered`:
   - odpalane sa efekty instant na kafelkach.

Gra konczy sie, gdy nie ma zywych championow.

## 6. Mapy i arena

### 6.1 Kodowanie mapy (`.gupb`)

Teren:

- `=`: `Sea` (nieprzechodnie, transparentne)
- `.`: `Land` (przechodnie, transparentne)
- `@`: `Forest` (przechodnie, nieprzezroczyste)
- `#`: `Wall` (nieprzechodnie, nieprzezroczyste, solid)

Bron jako loot:

- `K`: Knife
- `S`: Sword
- `A`: Axe
- `B`: Bow
- `M`: Amulet
- `C`: Scroll

### 6.2 Menhir

- Spawnuje sie na starcie gry.
- Na mapach `isolated_shrine` i `lone_sanctum` ma stale koordynaty `(9, 9)`.
- Na innych mapach pozycja jest losowa na pustym polu.

### 6.3 Widocznosc (FOV)

- Domyslnie ray-casting (Bresenham) zgodnie z kierunkiem postaci.
- Widocznosc blokuja nieprzezroczyste tile.
- Dodatkowo zawsze widoczne sa 2 sasiednie pola na boki.
- Wyjatek: `Amulet` (weapon prophetic) daje widocznosc kolowa (`prescience`), promien 3.

## 7. Champion

Statystyki startowe:

- HP: `8`
- bron: `Knife`
- facing: losowy

Kazdy champion ma:

- `controller` (instancja bota),
- `tabard` (kolor/skin z `preferred_tabard`).

### 7.1 Kara za kampienie (idle penalty)

- Po turze porownywane sa poprzednie i aktualne: `(position, facing)`.
- Jesli pozycja i facing sa identyczne, licznik idle rosnie.
- Jesli zmieni sie pozycja lub facing, licznik zeruje sie.
- Od 16 tur bez zmiany: `1 dmg` co ture.

Wniosek: samo krecenie sie zmienia facing, wiec unika idle penalty.

### 7.2 Smierc

Po smierci champion:

- znika z pola,
- zostawia `Potion`,
- zostawia bron tylko jesli bron jest `droppable`.

Opcjonalnie kontroler moze miec hook `die()`.

## 8. Akcje bota

Dostepne akcje (`characters.Action`):

- `TURN_LEFT`
- `TURN_RIGHT`
- `STEP_FORWARD`
- `STEP_BACKWARD`
- `STEP_LEFT`
- `STEP_RIGHT`
- `ATTACK`
- `DO_NOTHING`

Ruch jest relatywny do aktualnego `facing`.

## 9. Jakie dane dostaje bot (`ChampionKnowledge`)

W `decide()` bot dostaje:

- `position`
- `no_of_champions_alive`
- `visible_tiles`

`visible_tiles` to mapa `coords -> TileDescription` tylko dla tego, co aktualnie widac.
`TileDescription` zawiera:

- `type`
- `loot`
- `character`
- `consumable`
- `effects`

To jest POMDP: bot nie widzi calej mapy, potrzebuje pamieci lokalnej.

## 10. Itemy i bronie

### 10.1 Consumable

`Potion`:

- efekt: `+5 HP`,
- konsumowana automatycznie po wejsciu na pole.

### 10.2 Podnoszenie lootu

Po wejsciu na pole z bronia:

- bron jest podnoszona automatycznie,
- poprzednia bron zostaje na polu tylko gdy `droppable=True`.

### 10.3 Bronie (detale)

#### Knife

- zasieg: 1 w linii
- dmg: 2
- `droppable=False`

#### Sword

- zasieg: 3 w linii
- dmg: 2
- blokuje sie na pierwszym nieprzezroczystym obiekcie

#### Bow

- zasieg: 50 w linii
- dmg: 3
- tryb naprzemienny:
  - atak 1: ladowanie
  - atak 2: strzal

#### Axe

- uderza 3 pola przed graczem: lewy-przod, srodek-przod, prawy-przod
- dmg: 3

#### Amulet

- atak po przekatnych (odleglosc 1 i 2), 8 pol lacznie
- dmg: 2
- daje `prescience` (widocznosc kolowa, promien 3)

#### Scroll

- zasieg: 1
- 5 ladowan
- `droppable=False`
- naklada `Fire`

## 11. Efekty i obrazenia

Stale:

- `CUT_DAMAGE = 2`
- `MIST_DAMAGE = 1`
- `FIRE_DAMAGE = 3`

Efekty:

- `WeaponCut`: instant, jednorazowe obrazenia.
- `Fire`: eternal, obrazenia natychmiast i przy `stay`.
- `Mist`: eternal, obrazenia przy `stay`.

## 12. Mgla (battle royale pressure)

- Startowy promien mgly: `int(size_x * sqrt(2)) + 1`.
- Co `MIST_TTH_PER_CHAMPION * liczba_zywych` epizodow promien maleje o 1.
- Na granicy promienia nakladany jest efekt `Mist`.

## 13. Punktacja

Punkty sa liczone po koncu gry wg kolejnosci smierci.
Silnik uzywa rosnacej sekwencji z `_fibonacci()`:

- start: `1, 2, 3, 4, ...` (dalej wg wzoru z kodu).

Ostatni zywy champion tez trafia na liste "deaths" i dostaje najwyzszy wynik.

## 14. Kontrakt kontrolera

Bot musi miec:

- `decide(knowledge) -> Action`
- `praise(score) -> None`
- `reset(game_no, arena_description) -> None`
- property `name`
- property `preferred_tabard`

Opcjonalne hooki:

- `win()`
- `die()`

## 15. Rejestracja botow

Discovery botow dzieje sie przez skanowanie `gupb.controller.*` i czytanie `POTENTIAL_CONTROLLERS` z modulow.
Jezeli jakis modul nie importuje sie poprawnie, discovery moze sie wysypac.

## 16. Stan botow w aktualnym repo

- Dzialaja:
  - `RandomController`
  - `KeyboardController`
- Placeholdery (stala akcja):
  - `BenjaminNetanyahu`, `Bob`, `BladeRunner`, `SyntaxTerror`, `Pudzian`
- `JeffreyE`, `Karakin`: stale `ATTACK`
- `BIGbot`: parser obserwacji + stub, aktualnie `DO_NOTHING`
- `BiwakSpot`, `TheTrooper`: `NotImplementedError` w kluczowych metodach

## 17. Sterowanie reczne (KeyboardController)

- `X` na ekranie startowym: start
- `UP/DOWN/LEFT/RIGHT`: kroki relatywne
- `Z`: turn left
- `X`: turn right
- `SPACE`: attack

## 18. Logowanie i profilowanie

Logi:

- `verbose` -> plik `.log`
- `json` -> plik `.json` eventow

Profilowanie:

- dekorator `@profile` zapisuje czasy do `PROFILE_RESULTS`,
- `Runner.print_scores()` moze wydrukowac metryki wg `profiling_metrics` w configu.

## 19. Wazne wskazowki dla LLM

- Pilnuj zgodnosci z kontraktem `Controller`.
- Zmiany w walce zwykle dotykaja jednoczesnie:
  - `weapons.py`
  - `effects.py`
  - `tiles.py`
  - `games.py`
- Zmiany obserwacji bota wymagaja sprawdzenia:
  - `arenas.visible_coords`
  - `arenas.visible_tiles`
  - parserow obserwacji (np. `bigbot/observation_parser.py`)
- Testuj i tryb in-memory (`visualise=False`), i renderer (`visualise=True`).

## 20. Sciaga stalych gameplayowych

- HP start: `8`
- Heal potion: `+5`
- Idle penalty: po `16` turach bez zmiany pozycji i kierunku -> `1 dmg / ture`
- Dmg:
  - Knife/Sword/Amulet: `2`
  - Bow/Axe: `3`
  - Fire: `3`
  - Mist: `1`
- Bow: strzela co drugi atak
- Scroll: 5 ladowan, naklada fire, niedropowalny
