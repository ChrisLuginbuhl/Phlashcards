**Phlashcards**

Python 3

Uses Flask webserver to offer a series of cards for aiding memorization.
The cards have a title, text, image and a few other properties, stored in a database.
Database can be SQL local, Heroku/Postgre, or Airtable via API. 

Cards are served an optimal training frequency, i.e frequently at first, then with gradually decreasing frequency.

Since this may be served on the public web, a register/login/admin priviliges system is provided.

When running from a local database, uncomment the line "initialize_db()" near the bottom of main.py for first run, then comment it out again.

Use 127.0.0.1:5001/ for local host and to use the app. 
