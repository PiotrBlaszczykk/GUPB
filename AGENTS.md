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

Przy uruchamianiu konkretnego scenariusza uzyj:

```powershell
.\.venv\Scripts\python.exe -m gupb -c gupb/custom_configs/mixed_bots_parallel_config.py
```

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
- `runner_parallel.py`: odpalanie gier rownolegle (spawn/process pool) + dodatkowa observability.
- `model/`: cala logika gry.
- `view/render.py`: wizualizacja Pygame.
- `controller/`: boty i sterowanie reczne.
- `scripts/`: generator map i parser wynikow.
- `custom_configs/`: nasze niestandardowe konfiguracje symulacji.

## 4. Przeplyw wykonania

1. `python -m gupb` uruchamia `gupb.__main__.main`.
2. Ladowany jest `CONFIGURATION` z pliku config.
3. Na podstawie configu wybierany jest runner:
   - `RunnerParallel(config)`, gdy `parallel_processes > 1`, `visualise=False`, `inquiry=False`,
   - inaczej `Runner(config)`.
4. `Runner.run()` odpala `runs_no` gier.
5. Kazda gra to `Game` (state machine).
6. Na koncu `Runner.print_scores()` drukuje wyniki.

Wazne: wybor runnera nie jest "na sztywno" w configu.
Config podaje flagi (`parallel_processes`, `visualise`, `inquiry`), a decyzje podejmuje `gupb/__main__.py`.

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

- Dzialaja i sa aktywnie rozwijane:
  - `DummyBot` (`gupb/controller/dummy_bot/dummy_bot.py`) - solidny baseline heurystyczny.
  - `AgressiveBot` (`gupb/controller/agressive_bot/agressive_bot.py`) - wariant ofensywny.
  - `CowardBot` (`gupb/controller/coward_bot/coward_bot.py`) - wariant defensywny/camp.
  - `RandomController`
  - `KeyboardController`
- Pozostale kontrolery sa glownie eksperymentalne albo placeholderowe (warto sprawdzic kod przed uzyciem turniejowym).

### 16.1 Charakterystyka naszych 3 botow treningowych

- `DummyBot`:
  - pamiec mapy (`known_passable`, `known_blocked`, `visited_count`),
  - pamiec ostatnio widzianych przeciwnikow (TTL),
  - hazard avoidance, menhir mode, weapon-aware engage goals,
  - sluzy jako "balanced sparring baseline".
- `AgressiveBot`:
  - mocniej goni przeciwnikow i preferuje inicjacje walk,
  - ogranicza tylko ewidentnie samobojcze chase w mgle/na niskim HP.
- `CowardBot`:
  - unika walki, preferuje cover/forest i bezpieczne pozycje przy menhirze,
  - ma endgame switch, zeby domykac koncowki zamiast tylko przezywac.

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

### 18.1 Dodatkowe eventy w runnerze rownoleglym

W `runner_parallel.py` dochodza eventy:

- `ParallelChunkSubmittedReport`
- `ParallelChunkFinishedReport`
- `ParallelChunkFailedReport`
- `ParallelGameSummaryReport`
- `ParallelGameFailedReport`
- `ParallelRunSummaryReport`

Kazdy `ParallelGameSummaryReport` ma m.in.:

- `arena_name`, `episodes`, `winner_name`
- `scores` (punkty wszystkich kontrolerow)
- `mist_radius_end`, `menhir_x`, `menhir_y`

Uwaga: nazwy pol `dummy_*` w logu i czesc napisow w `print_scores()` sa historyczne
(nadal maja "dummy" w nazwie), nawet gdy testujesz innego bota.
To kwestia nazewnictwa observability, nie wynikow gry.

Profilowanie:

- dekorator `@profile` zapisuje czasy do `PROFILE_RESULTS`,
- `Runner.print_scores()` moze wydrukowac metryki wg `profiling_metrics` w configu.

## 19. Wazne wskazowki dla LLM

- Pilnuj zgodnosci z kontraktem `Controller`.
- Na turniej nie modyfikuj silnika (`model/*`, `areas.py`, `games.py`) bez potrzeby.
  Boty i eksperymenty trzymaj glownie w `controller/*` + configach.
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

## 21. Nasze custom configi (aktualny porzadek)

Wszystkie niestandardowe configi trzymamy w `gupb/custom_configs/`:

- `dummy_simulation_config.py`
- `agressive_config.py`
- `coward_config.py`
- `mixed_bots_config.py` (sekwencyjny: `parallel_processes=1`)
- `mixed_bots_parallel_config.py` (rownolegly: `parallel_processes=8`)
- `together_config.py`

Przyklady:

```powershell
# zwykly runner
.\.venv\Scripts\python.exe -m gupb -c gupb/custom_configs/mixed_bots_config.py

# runner rownolegly
.\.venv\Scripts\python.exe -m gupb -c gupb/custom_configs/mixed_bots_parallel_config.py
```

## 22. Interpretacja wynikow konsolowych

- Linie typu `1. BotName: 1234.` to suma punktow rankingowych z wielu gier.
- `First-place rates` to rzeczywisty winrate (ile razy bot byl 1.).
- Przy ocenie "kto dominuje" patrz najpierw na `First-place rates`, dopiero potem na punkty laczne.

## 23. Heurystyczny decision stack (praktyka z 3 botow)

Ponizszy porzadek decyzji okazal sie stabilny i przewidywalny:

1. Anti-stuck / failed-move recovery.
2. Natychmiastowe wyjscie z hazardu (`mist`/`fire`).
3. Lokalny combat:
   - adjacent enemy -> obrot i `ATTACK`,
   - enemy in weapon range -> `ATTACK`.
4. Menhir mode (gdy late-game/mist/niski HP).
5. Chase (tylko gdy nie jest samobojczy wg progow HP/mist/dystans).
6. Loot/potion target.
7. Explore / anchor / hide.

Warianty osobowosci:

- `DummyBot`: balanced (czasem chase, czasem menhir, sensowny loot).
- `AgressiveBot`: przesuwa priorytet na chase/fight.
- `CowardBot`: przesuwa priorytet na retreat/hide/menhir hold, ale musi miec endgame switch.

## 24. Weapon-aware zasady ruchu i walki

Sprawdzone heurystyki pod aktualna mechanike:

- `knife`:
  - chcemy adjacency,
  - nie chase'owac daleko na niskim HP.
- `sword`:
  - preferowac linie 1-3 pola,
  - nie trzeba "wchodzic pod nos".
- `axe`:
  - walka frontowym 3-polem (left-front, front, right-front),
  - dobra do presji w ciasnych strefach menhiru.
- `bow`:
  - dlugi zasieg, ale tryb ladowanie/strzal,
  - w late game i blisko menhiru nie zawsze jest najlepszy.
- `amulet`:
  - atak po przekatnych (1 i 2),
  - dodatkowo daje kolowa prescience.
- `scroll`:
  - strefowanie przez `fire`, ladunki ograniczone.

## 25. Pamiec stanu (POMDP) - co trzymac w kontrolerze

Minimalny sensowny zestaw:

- `known_passable`, `known_blocked`,
- `visited_count`,
- `recent_positions` (anty-petla),
- `enemy_memory` z TTL,
- `known_menhir`,
- `recent_damage` + `panic_turns`.

Dlaczego to dziala:

- bez pamieci bot wyglada "losowo",
- z pamiecia robi stabilny pathfinding i mniej marnuje tur,
- `panic_turns` broni przed glupim trade'em po naglym spike dmg.

## 26. Antywzorce i regression checklist

Rzeczy, ktore juz raz popsuly performance:

- BFS first-step mapowany na obrot zamiast kroku:
  - zly: `TURN_LEFT/RIGHT`,
  - poprawny: `STEP_LEFT/RIGHT/BACKWARD`.
- Retreat/hide reagujacy na "ghost enemy" z pamieci:
  - defensywa powinna bazowac glownie na wrogach widocznych teraz.
- Nadmiernie pasywny camper:
  - przezywa dlugo, ale nie domyka gier (duzo 2-4 miejsca).
- Dotykanie silnika gry pod turniej:
  - unikac zmian w `areas.py`/`model/*` jesli celem jest bot turniejowy.

## 27. Jak czytac logi pod tuning bota

Najbardziej uzyteczne sygnaly:

- `First-place rates`: glowny KPI.
- Rank histogram (`scores[bot]`): czy bot "nie domyka" (duzo 2-4).
- Arena breakdown: czy slabe mapy to open-space czy close-quarters.
- `avg episodes` i `longest game`: czy bot gra "za dlugo" bez finalizacji.
- `ParallelGameSummaryReport`:
  - winner, arena, episodes, score map.

Praktyczna petla strojenia:

1. Uruchom 200-400 gier na parallel configu.
2. Sprawdz per-arena WR i rozklad miejsc.
3. Modyfikuj 1-2 progi naraz (HP, dystans chase, menhir radius).
4. Powtorz run i porownaj tylko z poprzednim baseline.

## 28. Uzycie 3 botow jako sparring pool pod RL

Dobre role treningowe:

- `CowardBot`: uczy domykania pozycyjnego i walki w koncowkach.
- `DummyBot`: uczy gry z "normalnym" przeciwnikiem heurystycznym.
- `AgressiveBot`: uczy reakcji na presje i anti-rush.

Najprostszy curriculum:

1. Start: wiecej `CowardBot` i `Random` (stabilizacja przezycia).
2. Srodek: mix `DummyBot` + `Random`.
3. Koniec: wiecej `AgressiveBot` + `DummyBot` (presja + domykanie).

Wazne: trzymaj stale zasady silnika miedzy treningiem i ewaluacja.
