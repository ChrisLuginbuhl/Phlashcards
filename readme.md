**Phlashcards**

Python 3

Uses Flask webserver to offer a series of cards for aiding memorization.
The cards have a title, text, image and a few other properties, stored in a database.
Database can be SQL local, Heroku/Postgre, or Airtable via API. 

Cards are served an optimal training frequency, i.e frequently at first, then with gradually decreasing frequency.

Since this may be served on the public web, a register/login/admin priviliges system is provided.

When running from a local database, uncomment the line "initialize_db()" near the bottom of main.py for first run, then comment it out again.

Use 127.0.0.1:5001/ for local host and to use the app. 

Shield: [![CC BY-NC-SA 4.0][cc-by-nc-sa-shield]][cc-by-nc-sa]

This work is licensed under a
[Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License][cc-by-nc-sa].

[![CC BY-NC-SA 4.0][cc-by-nc-sa-image]][cc-by-nc-sa]

[cc-by-nc-sa]: http://creativecommons.org/licenses/by-nc-sa/4.0/
[cc-by-nc-sa-image]: https://licensebuttons.net/l/by-nc-sa/4.0/88x31.png
[cc-by-nc-sa-shield]: https://img.shields.io/badge/License-CC%20BY--NC--SA%204.0-lightgrey.svg