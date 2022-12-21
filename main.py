'''
Pimsleur Flashcards
Chris Luginbuhl

This flashcard web app is intended for learning & remembering anything - language, facts, stories, people's names...

It uses training frequency inspired by the Pimsleur language courses to ask you things just before you're about to
forget them, e.g. after 5 minutes, after 20 minutes, after an hour, after 1 day, 3, days, etc.
The newest flash cards are shown with the greatest frequency.

It is intended to be deployed using Heroku (for web access from anywhere) and Postgre (for database), or
using Airtable (for db) and Python Anywhere (now that Heroku is not free!)
The app also supports multiple users in the same database.

Makes use of some code from Udemy/App Brewery's 100 Days of Code day 64 and 69 for user registration, login, etc.
'''

import os
from flask import Flask, render_template, redirect, url_for, flash, request, abort
from flask_bootstrap import Bootstrap
from flask_ckeditor import CKEditor
from datetime import date
from datetime import timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin, login_user, LoginManager, login_required, current_user, logout_user
from forms import CreateCardForm, CreateCommentForm, RegisterForm, LoginForm
from secrets import token_hex
from functools import wraps
import random
from collections import namedtuple
import bleach
from pyairtable import Api, Base, Table
from pyairtable.formulas import match
from flask_debugtoolbar import DebugToolbarExtension

# Run Pydoc window with: python -m pydoc -p <port_number>

# TODO 1: Check all routes on debug toolbar "routes" e.g. /ckeditor/static/<path:filename> for login_required

QUEUE_SIZE = 3

# FREQUENCY_DECAY_RATE = 5  # lower number makes frequency of cards decline faster
EXP_WEIGHTS = [1.0, 0.8187307530779818, 0.6703200460356393, 0.5488116360940265, 0.44932896411722156,
               0.36787944117144233, 0.30119421191220214, 0.24659696394160652, 0.2018965179946554, 0.16529888822158656,
               0.1353352832366127, 0.11080315836233387, 0.09071795328941253, 0.07427357821433389, 0.06081006262521799,
               0.04978706836786395, 0.04076220397836622, 0.03337326996032609, 0.027323722447292562,
               0.022370771856165605]
# ^ calculated from this: exp_weights = [math.e ** -(f/FREQUENCY_DECAY_RATE) for f in range(0, MAX_INFREQUENCY)]
# (you also need to import math to run this)
# MAX_INFREQUENCY = 20  # num_views above which frequency stops declining

Card_data = namedtuple('Card_data', ['id', 'num_views', 'initial_frequency', 'weight'])

Flask.secret_key = token_hex(16)
app = Flask(__name__)
# app.config['SECRET_KEY'] = token_hex(32)
app.config['SECRET_KEY'] = os.environ.get('APP_SECRET_KEY')
ckeditor = CKEditor(app)
Bootstrap(app)
app.debug = True  # This is for debug toolbar

## CONNECT TO AIRTABLE AS DB
airtable_api_key = os.environ.get('AIRTABLE_API_KEY')
airtable_base_id = os.environ.get('AIRTABLE_BASE_ID')

airtable_cards_table_name = 'cards_table'
airtable_user_table_name = 'users_table'
api = Api(airtable_api_key)
card_table = Table(airtable_api_key, airtable_base_id, airtable_cards_table_name)
user_table = Table(airtable_api_key, airtable_base_id, airtable_user_table_name)
login_manager = LoginManager()
login_manager.init_app(app)

# toolbar = DebugToolbarExtension(app)


class User(UserMixin):
    def __init__(self, user_name, email, password_hash, id=0,):
        self.id = id
        self.user_name = user_name
        self.email = email
        self.password_hash = password_hash


class Schedule:

    # Creates a queue of cards according to these rules:
    # Pick QUEUE_SIZE cards randomly, according to weights
    # No duplicates in queue. Add new cards to end, remove from start
    # Don't add cards to queue if they are marked "skip for today"
    # returns the database id of the next card. This is a weighted random choice. Weights are calculated from the
    # initial_frequency, num_views (in db) and the weights that decrease with increasing number of views.
    #
    # Steps:
    # 1. Get all card id, initial_frequency, num_views, skip_for_today from database (don't load images, body, etc)
    # 2. Calculate weights (initial_frequency * exponential decay according to num views)
    # 3. Create a list of eligible cards (cards not in the queue already, not skip for today, etc)
    # 4. Pick a card from this list randomly, add it to the end of the queue
    # 5. repeat 3, 4 until queue is full
    # 6. Draw card from front of queue and display it, remove it from queue
    # 7. Repeat 1-6 forever

    def __init__(self):
        self.queue = []
        eligible_cards = self.get_all_card_info()
        for i in range(QUEUE_SIZE):
            try:
                self.queue.append(random.choices(eligible_cards, [card.weight for card in eligible_cards], k=1)[0])
                eligible_cards.pop(eligible_cards.index(self.queue[-1]))  # remove last added card from eligible
            # ^ Note this step is slow with large numbers of cards because it has to go through each card
            # For performance, also see 'using lists as queues' in
            # python docs: https://docs.python.org/3/tutorial/datastructures.html#more-on-lists
            except:
                print(
                    f'An error occurred while filling the queue. Possibly not enough cards to fill queue of {QUEUE_SIZE}')
        print(f'queue is: {self.queue}')

    def get_all_card_info(self):
        # Retrieves data from all cards in database and returns it in a list of
        # named tuples including calculated weights
        card_data = card_table.all()
        ids = [card['fields']['card_id'] for card in card_data]
        num_views = [card['fields']['num_views'] for card in card_data]
        initial_frequencies = [card['fields']['initial_frequency'] for card in card_data]
        weights = [init_freq * EXP_WEIGHTS[num_views[idx]] for idx, init_freq in enumerate(initial_frequencies)]
        # ^ weights are calculated as: (initial frequency) * (exp_weight corresponding to num_views)
        return [Card_data(id, num_views[idx], initial_frequencies[idx], weights[idx]) for idx, id in enumerate(ids)]
        # ^ List comp of named tuples "Card_data"

    # def adjust_frequency(self, card_id: int, adj=1):

    def get_next_card(self) -> int:
        # queue = list(dict.fromkeys(queue))  # removes duplicates
        card = self.queue.pop(0)
        all_cards = self.get_all_card_info()
        eligible_cards = [card for card in all_cards if card not in self.queue]
        self.queue.append(random.choices(eligible_cards, [card.weight for card in eligible_cards], k=1)[0])
        return card.id


# HELPER FUNCTIONS
def make_hash(password):  # returns 'method:salt:hash'
    return generate_password_hash(password, method='pbkdf2:sha256', salt_length=16)


# This function is required by Flask Login Manager.
@login_manager.user_loader
def load_user(id):
    user_data = user_table.first(formula=match({"user_id": id}))['fields']
    user = User(
        id=user_data['user_id'],
        user_name=user_data['user_name'],
        email=user_data['email'],
        password_hash=user_data['password_hash']
    )
    return user


def is_admin():
    # User with id 1 in database is the admin for the blog
    if current_user.is_authenticated and current_user.id == 1:
        return True
    else:
        return False


# Decorator functions
def admin_only(func):
    @wraps(func)
    # This line is required so that flask doesn't see the multiple routes assigned to the same function ('wrapper')
    #  See https://stackoverflow.com/questions/17256602/assertionerror-view-function-mapping-is-overwriting-
    #  an-existing-endpoint-functi
    def wrapper(*args, **kwargs):
        if not is_admin() or current_user.is_anonymous:
            # flash('403 Not authorized. Please log in as admin')
            # return redirect(url_for('login'), 403)
            abort(403)
        return func(*args, **kwargs)
    return wrapper


def logged_in_only(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('login'))
        return func(*args, **kwargs)
    return wrapper



@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        formula = match({"email": request.form.get('email').lower()})
        user_data_raw = user_table.first(formula=formula)
        if user_data_raw:
            user_data = user_data_raw['fields']
            print(f'Trying to add email: {request.form.get("email")}. Found: {user_data["email"]}')
            flash('Email already in use. Log in instead')
            return redirect(url_for('login'))
        response_from_db = user_table.create(
            {'user_name':request.form.get('name'),
            'email':request.form.get('email').lower(),
            'password_hash':make_hash(request.form.get('password'))},
        )
        print(f'Registered new user with database: {response_from_db}')
        user_data = response_from_db['fields']
        user = User(
            id=user_data['user_id'],
            user_name=user_data['user_name'],
            email=user_data['email'],
            password_hash=user_data['password_hash']
        )
        # user.id = user.user_id
        login_user(user)
        flash('Registered and logged in')
        return redirect(url_for('get_all_cards'))
    return render_template("register.html", form=form)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('show_card'))
    form = LoginForm()
    if request.method == 'POST':
        # user = User.query.filter_by(email=request.form.get('email').lower()).first()
        formula = match({"email": request.form.get('email')})
        user_data = user_table.first(formula=formula)['fields']
        user = User(
            id=user_data['user_id'],
            user_name=user_data['user_name'],
            email=user_data['email'],
            password_hash=user_data['password_hash']
        )
        print(f'User: {user}')
        if user:
            if check_password_hash(user.password_hash, request.form.get('password')):
                login_user(user)
                flash('Logged in successfully.')
                return redirect(url_for('show_card'))
            else:
                flash('Password incorrect.')
        else:
            flash('Email not registered')
    return render_template('login.html', form=form, logged_in=current_user.is_authenticated)


@app.route('/logout')
def logout():
    logout_user()
    flash("Logged out")
    return redirect(url_for('login'))



@app.route("/")
# @logged_in_only
def show_card():
    card_id = request.args.get("card_id")
    if not card_id:
        card_id =sched.get_next_card()
    requested_card = card_table.first(formula=match({"card_id": card_id}))['fields']
    return render_template("card_and_image.html",
                           card=requested_card,
                           # comments=comments,
                           # form=comment_form,
                           is_admin=is_admin(),
                           logged_in=current_user.is_authenticated,
                           dark_mode=False,
                           )


@app.route('/index')
@logged_in_only
def get_all_cards():
    card_data_raw = card_table.all(fields=['card_id', 'title', 'body', 'author', 'date_created'])
    card_data_unsorted = [card["fields"] for card in card_data_raw]
    card_data = sorted(card_data_unsorted, key=lambda card: card['card_id'])
    print(f'card data: {card_data}')
    return render_template("index.html",
                           all_cards=card_data,
                           logged_in=current_user.is_authenticated,
                           is_admin=is_admin()
                           )


@app.route("/card/<int:card_id>", methods=['GET', 'POST'])
@logged_in_only
def add_comment(card_id):
    card_id = request.args.get("id")
    if not card_id:
        requested_card = Flashcard.query.get(card_id)
    comments = Comment.query.filter_by(parent_card=requested_card)
    comment_form = CreateCommentForm()

    if comment_form.validate_on_submit():
        if not current_user.is_authenticated:
            flash("You must be logged in to comment")
            return redirect(url_for('login'))
        comment = Comment(
            comment_author=current_user,
            text=comment_form.body.data,
            parent_card_id=card_id,
            # date=date.today().strftime("%B %d, %Y")
        )
        db.session.add(comment)
        db.session.commit()
        flash("Comment submitted successfully")
    return render_template("card_and_image.html",
                           card=requested_card,
                           # comments=comments,
                           # form=comment_form,
                           is_admin=is_admin(),
                           logged_in=current_user.is_authenticated,
                           dark_mode=True,
                           )


@app.route("/new-card", methods=['GET', 'POST'])
@logged_in_only
def add_new_card():
    form = CreateCardForm()
    if form.validate_on_submit():
        # clean_html_body = BeautifulSoup(form.body.data).get_text()
        new_card = Flashcard(
            title=form.title.data,
            body=bleach.clean(form.body.title),
            img_url=form.img_url.data,
            author=current_user,
            reverse_body="Nothing here",
            date_created=date.today().strftime("%B %d, %Y"),
            last_viewed=date.today().strftime("%B %d, %Y"),
            num_views=0,
            initial_frequency=1,
        )
        db.session.add(new_card)
        db.session.commit()
        return redirect(url_for("get_all_cards"))
    return render_template("new-card.html", form=form)


@app.route("/edit-card/<int:card_id>", methods=['GET', 'POST'])
@admin_only
def edit_card(card_id):
    print('running edit_card')
    card = Flashcard.query.get(card_id)
    edit_form = CreateCardForm(
        title=card.title,
        img_url=card.img_url,
        author=card.author,
        body=card.body,
    )
    if edit_form.validate_on_submit():
        card.title = edit_form.title.data
        card.img_url = edit_form.img_url.data
        # card.author = edit_form.author.data
        card.body = edit_form.body.data
        db.session.commit()
        return redirect(url_for("show_card", card_id=card.id))
    print(f'rendering new card template. Login status: {current_user.is_authenticated}')
    return render_template("new-card.html", logged_in=current_user.is_authenticated, is_edit=True, form=edit_form)


@app.route("/delete-card/<int:card_id>")
@admin_only
def delete_card(card_id):
    card_to_delete = Flashcard.query.get(card_id)
    db.session.delete(card_to_delete)
    db.session.commit()
    return redirect(url_for('get_all_cards'))


@app.route("/about")
def about():
    return render_template("about.html")


@logged_in_only
@app.route("/contact")
def contact():
    return render_template("contact.html")

# initialize_db()  # only need to do this the first time the code is run
sched = Schedule()

if __name__ == "__main__":
    app.run(host='127.0.0.1', port=5001)
