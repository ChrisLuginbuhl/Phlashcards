from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, IntegerField, PasswordField
from wtforms.validators import DataRequired, URL, NumberRange
from flask_ckeditor import CKEditorField
import global_constants as gc

# from main import FREQUENCY_DECAY_RATE_MAX, FREQUENCY_DECAY_DEFAULT, INITIAL_FREQUENCY_MAX, INITIAL_FREQUENCY_DEFAULT
##WTForm
class CreateCardForm(FlaskForm):
    title = StringField("Blog Post Title", validators=[DataRequired()])
    img_url = StringField("Blog Image URL", validators=[URL()])
    num_views = IntegerField("Number of Views", validators=[DataRequired()])
    initial_frequency = IntegerField(f"Initial Frequency (1 = v. low, {gc.INITIAL_FREQUENCY_MAX} = very high, "
                                     f"default={gc.INITIAL_FREQUENCY_DEFAULT})",
                                     validators=[DataRequired(), NumberRange(min=1, max=10,
                                     message=f'Initial Frequency must be an integer between 1 '
                                             f'and {gc.INITIAL_FREQUENCY_MAX}')])
    frequency_decay = IntegerField(f"Frequency Decay (1=v. slow, {gc.FREQUENCY_DECAY_RATE_MAX} = v. fast, "
                                   f"default={gc.FREQUENCY_DECAY_DEFAULT})",
                                   validators=[DataRequired(),
                                               NumberRange(min=1, max=gc.FREQUENCY_DECAY_RATE_MAX,
                                     message=f'Frequency Decay must be an integer '
                                             f'between 1 and {gc.FREQUENCY_DECAY_RATE_MAX}')])
    body = CKEditorField("Blog Content")
    submit = SubmitField("Submit Post")


class CreateCommentForm(FlaskForm):
    body = CKEditorField("Add a Comment", validators=[DataRequired()])
    submit = SubmitField("Submit Comment")


class RegisterForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired()])
    name = StringField("Username", validators=[DataRequired()])
    submit = SubmitField('Sign me up!')

class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField('Log me in')
