import config
import referrals
import logging
import database
import openai

# setup
from aiogram import Bot, Dispatcher, executor, types
from aiogram.types.message import ContentType
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters import Text
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import ParseMode
from aiogram.utils import executor
logging.basicConfig(level=logging.INFO)

openai.api_key = config.OPENAI_TOKEN

# init
bot = Bot(token=config.TELEGRAM_TOKEN)

storage = MemoryStorage()
# Create dispatcher object
dp = Dispatcher(bot, storage=storage)

#initialize mongoDB
DataStorage = database.DataStore()
# Define states
class ChatState(StatesGroup):
    waiting_for_message = State()

# commands
@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    # Check if the message contains the referral parameter
    referral_user_id = referrals.decode_payload(message.get_args())
    if referral_user_id and referral_user_id != -1:
        referral_user_id = int(referral_user_id.split("_")[-1])
        # Check if the user is using own referral link
        if int(referral_user_id) == message.from_user.id:
            await message.reply('Ей ти, в морду дати? Своє реферал посилання не можна юзати')
        # Check if user was already referred
        elif DataStorage.checkUserInDB(message.from_user.id):
            await message.reply("Ви вже були зареферені") # this message is for debug purposes only, in final script, we'll remove that
        else:
            #add user to the db
            DataStorage.createUser(message.from_user.id)
            # Increment the referral counter for the user who referred someone
            referrals_counter = DataStorage.getReferrals(referral_user_id) + 1
            DataStorage.updateReferrals(referral_user_id, referrals_counter)

            # Check if the referral count has reached 3 and send congratulations message
            if referrals_counter == 3:
                DataStorage.updateReferrals(referral_user_id,0)
                questions_counter = DataStorage.getQuestions(referral_user_id) + 1
                DataStorage.updateQuestions(referral_user_id, questions_counter)
                await bot.send_message(int(referral_user_id), "Вітаю! Троє людей долучились через ваше посилання")
    await bot.send_message(message.chat.id,
                           "Привіт, я допомагаю закривати сесію, я можу продати тобі відповіді на твої запитання.\n"
                           "Напиши /question (тест)щоб задати питання\n/buy щоб купити відповіді\n/terms для умов\n/referral_link для генерації рефералки\n/referral_status для перевірки к-сті зареференних юзерів\n/questions_status для перевірки к-сті питань\n/cancel відмінити генерацію відповіді")

@dp.message_handler(commands=["terms"])
async def process_terms_command(message: types.Message):
    await bot.send_message(message.chat.id,
                           "Купіть відповіді на ваші запитання, оплата дає вам 3 відповіді на запитання")
    
@dp.message_handler(commands=['referral_link'])
async def unique_link_command_handler(message: types.Message):
    user_id = referrals.encode_payload(message.from_user.id)
    referral_link = f'Тут є <a href="tg://resolve?domain=asjhdkaksjbot&start={user_id}">реферальне посилання</a>'

    # Send the referral link to the user
    await bot.send_message(
        message.chat.id,
        referral_link,
        parse_mode='HTML'
    )

@dp.message_handler(commands=['referral_status'])
async def check_referrals_command_handler(message: types.Message):
    # Get the referral count for the user
    count = DataStorage.getReferrals(message.from_user.id)
    # Send the referral count to the user
    await bot.send_message(
        message.chat.id,
        f"{count} людей використали твоє посилання"
    )

@dp.message_handler(commands=['questions_status'])
async def check_questions_command_handler(message: types.Message):
    # Get the referral count for the user
    count = DataStorage.getQuestions(message.from_user.id)
    # Send the referral count to the user
    await bot.send_message(
        message.chat.id,
        f"Залишилося {count} питань"
    )

PRICE = types.LabeledPrice(label="Купити", amount=200*100)

# buy
@dp.message_handler(commands=["buy"])
async def buy(message: types.Message):
    if config.PAYMENT_TOKEN.split(":")[1] == 'TEST':
        await bot.send_message(message.chat.id, "Test payment!")
    await bot.send_message(message.chat.id,
                           "Починаємо процес оплати"
                           "\n\nЦе ваш інвойс:", parse_mode='Markdown')
    await bot.send_invoice(
        message.chat.id,
        title="Купити",
        description="Оплата за 3 запитання від бота",
        provider_token=config.PAYMENT_TOKEN,
        currency="uah",
        photo_url="https://telegra.ph/file/d08ff863531f10bf2ea4b.jpg",
        photo_width=416,
        photo_height=234,
        photo_size=416,
        is_flexible=False, # we don't need shipping fee
        prices=[PRICE],
        start_parameter="one-month-subscription",
        payload="test-invoice-payload"
    )

# pre checkout (10 seconds to answer)
@dp.pre_checkout_query_handler(lambda query: True)
async def pre_checkout_query(pre_checkout_q: types.PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_q.id, 
                                        ok=True,
                                        error_message="Упс, щось пішло не так")

# payment completion
@dp.message_handler(content_types=ContentType.SUCCESSFUL_PAYMENT)
async def successful_payment(message: types.Message):
    print("Оплата успішна:")
    payment_info = message.successful_payment.to_python()
    for key, value in payment_info.items():
        print(f"{key} = {value}")
    questions_counter = DataStorage.getQuestions(message.from_user.id) + 3
    DataStorage.updateQuestions(message.from_user.id, questions_counter)
    await bot.send_message(message.chat.id, f"Оплата по сумі {message.successful_payment.total_amount // 100} {message.successful_payment.currency} пройшла")

class ChatState(StatesGroup):
    waiting_for_message = State()

# Define handler for messages
@dp.message_handler(Text(equals='cancel', ignore_case=True), state=ChatState.waiting_for_message)
async def cancel_handler(message: types.Message, state: FSMContext):
    # Cancel the current operation and return to the initial state
    await state.finish()
    await message.reply("Cancelled.")

@dp.message_handler(commands=['question'])
async def start_handler(message: types.Message):
    if DataStorage.checkQuestionsLeft(message.from_user.id):
        # Ask the user to send a message to start the conversation
        await message.reply("Hi there! Send me a message to get started.")
        # Set the state to waiting_for_message
        # This code should be done after successful payment
        await ChatState.waiting_for_message.set()
    else:
        await message.reply("Та заплати вже йой, замахав:(")

@dp.message_handler(state=ChatState.waiting_for_message)
async def handle_message(message: types.Message, state: FSMContext):
    # Call the OpenAI API to get the response

    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "Ти є живою людиною-студентом, який відповідає на запитання сесії"},
            {"role": "user", "content": message.text}
        ]
    )
    # Send the response back to the user
    await message.answer(response.choices[0].message.content)
    count = DataStorage.getQuestions(message.from_user.id) - 1
    DataStorage.updateQuestions(message.from_user.id, count)
    # Set the state to waiting_for_message
    await state.finish()

# run
if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)