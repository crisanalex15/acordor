# Acordor — tuner pentru chitară, bass și ukulele

Aplicație desktop (Python + pygame) care ascultă microfonul, detectează nota cântată
și arată cât de departe e de coarda corectă, în cents (1/100 dintr-un semiton).

## Pornire

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Teste: `python -m unittest discover -s tests -t .`

## Utilizare

- **Auto**: ciupești orice coardă, aplicația recunoaște singură care e.
- **Coardă manuală**: click pe o coardă de jos. Încă un click revine la Auto.
- **Cromatic**: orice notă, comparată cu cel mai apropiat semiton.
- O coardă ținută acordată ~0.6 s primește o bifă verde.
- **A4**: calibrarea notei de referință (implicit 440 Hz), cu butoanele − / +.

Taste: `A` auto · `C` cromatic · `1`–`6` coarda · `I` instrument · `M` microfon · `+`/`−` A4 · `Esc` ieșire.

## Arhitectură

```
microfon ─► audio_capture.py ─► pitch.py ─► tracker.py ─► tuner.py ─► ui.py
            ring buffer          YIN         median +      coardă țintă,  pygame
            (thread PortAudio)   (Hz)        netezire,     cents, bife
                                             hold
```

| Fișier | Rol |
|---|---|
| `audio_capture.py` | Stream de intrare non-blocant (WASAPI pe Windows), ring buffer de 1 s. |
| `pitch.py` | Algoritmul YIN: funcția diferență prin FFT, normalizare cumulativă, prag absolut, interpolare parabolică. |
| `tracker.py` | Stabilizare: respinge vârfurile izolate, median pe 5 citiri, netezire exponențială, ține nota 1.5 s. |
| `notes.py` | Note, instrumente, conversii Hz ↔ MIDI ↔ cents. |
| `tuner.py` | Logica tunerului (fără interfață): mod, coarda țintă, indicații, corzi acordate. |
| `ui.py` | Desenul și animațiile (acul are un arc amortizat critic). |
| `main.py` | Bucla principală la 60 FPS. |

## Precizie

Testele din `tests/test_pitch.py` folosesc semnale sintetice cu armonici (inclusiv cu
fundamentala mai slabă decât armonica a doua, ca la corzile groase) și zgomot:

- eroare mediană < 0.5 cents și maximă < 1.5 cents pe toate corzile celor 3 instrumente;
- fără erori de octavă;
- zgomotul alb și liniștea nu produc citiri.

Toleranța pentru „Acordat” este ±5 cents.
