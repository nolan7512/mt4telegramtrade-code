#!/usr/bin/env python3
import asyncio
import logging
import math
import os
import re
import json
import pytz
import configparser


try:
    from typing import Literal
except ImportError:
    from typing_extensions import Literal

from metaapi_cloud_sdk import MetaApi
from prettytable import PrettyTable
from telegram import ParseMode, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CommandHandler,
    Filters,
    MessageHandler,
    Updater,
    ConversationHandler,
    CallbackContext,
    CallbackQueryHandler,
    ContextTypes,
)
from datetime import datetime


config = configparser.ConfigParser()
config.read("/etc/secrets/secret_telegramtomt4.env")

# Define states for the conversation
SELECT_OPTION, WAIT_FOR_ID, INPUT_TEXT, ACTION_SELECT = range(4)

# Callback data
(
    SELECT_INFO,
    SELECT_POSITION,
    SELECT_ORDER,
    SELECT_TRAILING,
    SELECT_CLOSEFULL,
    SELECT_CLOSEPART,
) = (
    "select_info",
    "select_position",
    "select_order",
    "select_trailing",
    "select_closefull",
    "select_closepart",
)


(
    TRAILING_STOP,
    CLOSE_POSITION,
    CLOSEPART,
    ACCOUNT_INFO,
    OPENING_POSITION,
    PENDING_ORDER,
) = (
    "trailing_stop",
    "close_position",
    "select_closepart",
    "account_info",
    "opening_position",
    "pending_order",
)

# Create a list to store selected option and IDs
selected_data = {"option": None, "ids": []}


# MetaAPI Credentials
API_KEY = config["MetaAPI"]["API_KEY"]
ACCOUNT_ID = config["MetaAPI"]["ACCOUNT_ID"]
# Risk factor
RISK_FACTOR = float(config["MetaAPI"]["RISK_FACTOR"])
RISK_PERTRADE = float(config["MetaAPI"]["RISK_PERTRADE"])


# Telegram Credentials
TOKEN = config["Telegram"]["TOKEN"]
TELEGRAM_USER = config["Telegram"]["TELEGRAM_USER"].split(",")
AUTHORIZED_USERS = TELEGRAM_USER
CHANNEL_USER = config["Telegram"]["CHANNEL_USER"]


# Render Credentials
APP_URL = config["Render"]["APP_URL"]
# Port number for Telegram bot web hook
PORT = int(config["Render"].get("PORT", "8443"))
PLAN = config["Render"].get("PLAN", "A")
TRAILINGSTOP = config["Render"].get("TRAILING_STOP", "Y")

# Enables logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# possibles states for conversation handler
CALCULATE, TRADE, DECISION, ERROR = range(4)

# allowed FX symbols
# Đọc các biến từ file .env và chuyển thành danh sách
SYMBOLS = config["Bot"].get("SYMBOLS").split(",")
SYMBOLSPLUS = config["Bot"].get("SYMBOLSPLUS").split(",")
TYPETRADE = config["Bot"].get("TYPETRADE").split(",")
OTHER = config["Bot"].get("OTHER").split(",")


def update_env(text):
    """Cập nhật các biến môi trường từ text.

    Args:
      text: Đoạn text chứa các biến môi trường.

    Returns:
      None.
    """

    # Tạo đối tượng configparser.
    config = configparser.ConfigParser()

    # Đọc tệp cấu hình my_secret.
    config.read("/etc/secrets/my_secret.env")

    # Xử lý text.
    for line in text.splitlines():
        # Tìm kiếm một biến môi trường hợp lệ.
        match = re.match(r"([A-Za-z0-9_]+)\s*=\s*(.*)", line)
        if match:
            # Lấy tên và giá trị của biến môi trường.
            name = match.group(1)
            value = match.group(2)

            # Tìm kiếm biến môi trường trong tệp cấu hình.
            if name in config:
                # Cập nhật giá trị của biến môi trường.
                config[name] = value

    # Ghi lại các thay đổi vào tệp cấu hình.
    with open("/etc/secrets/my_secret.env", "w") as f:
        config.write(f)


def command_updateenv(update: Update, context: CallbackContext) -> int:
    """Sends a message to the user requesting text to update the environment.

    Arguments:
      updates: update from Telegram
      context: CallbackContext object that stores commonly used objects in handler callbacks
    """

    update.effective_message.reply_text(
        "Please enter the text to update the environment."
    )

    return INPUT_TEXT


# Function to start the conversation
def menu_button(update: Update, context: CallbackContext) -> int:
    # Send the menu with options
    reply_markup = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Account Info", callback_data=SELECT_INFO)],
            [InlineKeyboardButton("Opening Positions", callback_data=SELECT_POSITION)],
            [InlineKeyboardButton("Pending Orders", callback_data=SELECT_ORDER)],
            [InlineKeyboardButton("Trailing Stop", callback_data=SELECT_TRAILING)],
            [InlineKeyboardButton("Close Position", callback_data=SELECT_CLOSEFULL)],
            [
                InlineKeyboardButton(
                    "Close Part Position", callback_data=SELECT_CLOSEPART
                )
            ],
        ]
    )
    update.effective_message.reply_text(
        "Please choose an option:", reply_markup=reply_markup
    )
    return SELECT_OPTION


# Function to handle user's choice
def select_option(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    # await query.answer()
    data = query.data
    query.edit_message_text(text=f"Selected option: {data}")

    # text = update.message.text
    # update.effective_message.reply_text(text)

    # Update selected_data based on user's choice
    if data == SELECT_TRAILING:
        selected_data["option"] = TRAILING_STOP
        # Ask for IDs
        update.effective_message.reply_text(
            "Please send the position ID(s) separated by commas."
        )
        return WAIT_FOR_ID
    elif data == SELECT_CLOSEFULL:
        selected_data["option"] = CLOSE_POSITION
        # Ask for IDs
        update.effective_message.reply_text(
            "Please send the position ID(s) separated by commas."
        )
        return WAIT_FOR_ID
    elif data == SELECT_CLOSEPART:
        selected_data["option"] = SELECT_CLOSEPART
        # Ask for IDs
        update.effective_message.reply_text(
            "Please send the position ID(s) separated by commas."
        )
        return WAIT_FOR_ID
    elif data == SELECT_INFO:
        selected_data["option"] = ACCOUNT_INFO
        update.effective_message.reply_text(
            "OK! Check your account"
        )
        asyncio.run(account_info(update))
        selected_data.clear()
        return ConversationHandler.END
    elif data == SELECT_POSITION:
        selected_data["option"] = OPENING_POSITION
        update.effective_message.reply_text(
            "OK! Check your opening position"
        )
        asyncio.run(open_trades(update, context))
        selected_data.clear()
        return ConversationHandler.END
    elif data == SELECT_ORDER:
        selected_data["option"] = PENDING_ORDER
        update.effective_message.reply_text(
            "OK! Check your pending order"
        )
        asyncio.run(pending_orders(update, context))
        selected_data.clear()
        return ConversationHandler.END
     
    return  ConversationHandler.END


# Function to handle IDs and perform actions
def handle_ids(update: Update, context: CallbackContext) -> None:
    # Extract IDs from the message
    ids = update.message.text
    update.effective_message.reply_text(f" ids : " + ids)
    # Store IDs in selected_data
    selected_data["ids"] = ids

    # Perform actions based on user's choice
    option = selected_data["option"]
    update.effective_message.reply_text(f" handle_ids option : " + option)
    if option == TRAILING_STOP:
        # Call your function to handle trailing stop
        asyncio.run(trailing_stop(update, ids))
    elif option == CLOSE_POSITION:
        # Call your function to handle close position
        asyncio.run(close_position(update, ids))
    elif option == SELECT_CLOSEPART:
        # Call your function to handle close part position
        asyncio.run(close_position_partially(update, ids))
    # Reset selected_data for future use
    selected_data.clear()

    return ConversationHandler.END


# Function to handle IDs and perform actions
def handle_selectaction(update: Update, context: CallbackContext) -> None:
    # Perform actions based on user's choice
    option = selected_data["option"]
    logger.info(f"--------------------------handle_selectaction-------------------------------:  {option}")
    update.effective_message.reply_text(f" Action  : {option} ")
    if option == ACCOUNT_INFO:
        # Call your function to handle account info
        asyncio.run(account_info(update))
    elif option == OPENING_POSITION:
        # Call your function to handle opening position
        asyncio.run(open_trades(update, context))
    elif option == PENDING_ORDER:
        # Call your function to handle pending order
        asyncio.run(pending_orders(update, context))

    # Reset selected_data for future use
    selected_data.clear()

    return ConversationHandler.END


def ConvertDateTime(date) -> str:
    """Convert datetime object to string

    Arguments:
    date {datetime} -- datetime object

    Returns:
    str -- string of datetime object
    """
    # Chuỗi thời gian từ ISO 8601
    iso_time = date

    # Chuyển đổi sang đối tượng datetime
    datetime_obj_utc = datetime.fromisoformat(iso_time[:-1])  # Loại bỏ 'Z' ở cuối
    datetime_obj_utc = datetime_obj_utc.replace(tzinfo=pytz.UTC)  # Đặt múi giờ là UTC

    # Chuyển đổi sang múi giờ UTC+7
    timezone_utc7 = pytz.timezone("Asia/Bangkok")
    datetime_obj_utc7 = datetime_obj_utc.astimezone(timezone_utc7)

    # Chuyển đổi sang định dạng chuỗi mong muốn (dd-mm-yyyy)
    formatted_time = datetime_obj_utc7.strftime("%d-%m-%Y")

    return formatted_time


# Helper Functions
def CheckSymbolArray(stringcheck, array) -> int:
    """Check string in array if True return 1m if fasle return 0

    Arguments:
        stringcheck : string input for find in array
        array       : array for foreach find string input
    """
    checkstr = 0
    for element in array:
        calcu = stringcheck.upper().find(element, 0)
        if calcu != -1:
            checkstr = 1
            return checkstr
    return checkstr


def CheckSymbolStr(stringcheck, stringsrc) -> int:
    """Check string in array if True return 1m if fasle return 0

    Arguments:
        stringcheck : string input for find in array
        array       : array for foreach find string input
    """
    checkstr = 0
    calcu = stringsrc.find(stringcheck, 0)
    if calcu != -1:
        checkstr = 1
        return checkstr
    return checkstr


def FindTP(alphacheck, signalsrc) -> float:
    arrayfind = []
    alphacheck = alphacheck.lower()
    for i in range(len(signalsrc)):
        if signalsrc[i] != "":
            j = signalsrc[i].lower().find(alphacheck, 0)
            if j != -1:
                try:
                    tpfindvar = float((signalsrc[i].split())[-1])
                    arrayfind.append(tpfindvar)
                except ValueError:
                    pass
    return arrayfind


def calculate_rr_coefficient(take_profit_pips, stop_loss_pips):
    rr_coefficients = []

    for tp in take_profit_pips:
        rr_coefficient = float(tp / stop_loss_pips)
        rr_coefficients.append(rr_coefficient)

    return rr_coefficients


def remove_pips(signal):
    temp = re.sub(
        r"(pips|\(.+\))|(pip|\(.+\))|(scalper|\(.+\))|(intraday|\(.+\))|(swing|\(.+\))",
        "",
        signal,
    )
    return temp


# Lấy danh sách pending orders
async def get_pending_orders(update: Update):
    try:
        api = MetaApi(API_KEY)
        account = await api.metatrader_account_api.get_account(ACCOUNT_ID)
        initial_state = account.state
        deployed_states = ["DEPLOYING", "DEPLOYED"]

        if initial_state not in deployed_states:
            #  wait until account is deployed and connected to broker
            logger.info("Deploying account")
            await account.deploy()

        logger.info("Waiting for API server to connect to broker ...")
        await account.wait_connected()

        # connect to MetaApi API
        connection = account.get_rpc_connection()
        await connection.connect()

        # obtains account information from MetaTrader server
        orders = await connection.get_orders()
        return orders
    except Exception as e:
        print(f"Error getting pending orders: {e}")
        update.effective_message.reply_text(f"Error getting open trades: {e}")
        return []


# Lấy danh sách open trades
async def get_open_trades(update: Update):
    try:
        api = MetaApi(API_KEY)
        account = await api.metatrader_account_api.get_account(ACCOUNT_ID)
        initial_state = account.state
        deployed_states = ["DEPLOYING", "DEPLOYED"]

        if initial_state not in deployed_states:
            #  wait until account is deployed and connected to broker
            logger.info("Deploying account")
            await account.deploy()

        logger.info("Waiting for API server to connect to broker ...")
        await account.wait_connected()

        # connect to MetaApi API
        connection = account.get_rpc_connection()
        await connection.connect()

        # wait until terminal state synchronized to the local state

        # obtains account information from MetaTrader server
        trades = await connection.get_positions()
        return trades
    except Exception as e:
        logger.info(f"Error getting open trades: {e}")
        update.effective_message.reply_text(f"Error getting open trades: {e}")
        return []


def create_table(data, is_pending=True) -> PrettyTable:
    try:
        # Kiểm tra xem data có phải là chuỗi không
        if isinstance(data, str):
            # Nếu là chuỗi, chuyển đổi thành đối tượng Python
            json_data = json.loads(data)
        elif isinstance(data, list):
            # Nếu là danh sách, sử dụng trực tiếp
            json_data = data
        else:
            # Nếu không phải là chuỗi hoặc danh sách, xử lý lỗi hoặc trả về
            raise ValueError("Invalid data format")

        table = PrettyTable()
        headers = ["Id", "Type", "Symbol", "Size", "Entry", "SL", "TP", "Profit"]
        table.align["Id"] = "l"
        table.align["Type"] = "l"
        table.align["Symbol"] = "l"
        table.align["Size"] = "l"
        table.align["Entry"] = "l"
        table.align["SL"] = "l"
        table.align["TP"] = "l"
        table.align["Profit"] = "l"
        if not is_pending:
            data_key = "positions"
            table.title = "Opening Trades"
        else:
            data_key = "orders"
            table.title = "Pending Orders"
            if "Profit" in headers:
                headers.remove("Profit")

        table.field_names = headers
        total_profit = 0
        for order_or_position in json_data:
            # Truy cập thông tin từng vị thế hoặc order tùy thuộc vào loại dữ liệu
            if data_key == "positions":
                order_type = order_or_position.get("type", "")
                profit_value = round(float(order_or_position.get("profit", 0)), 2)
                if profit_value >= 0:
                    profit_with_currency = f"{profit_value:,.2f} $"
                else:
                    profit_with_currency = f"{profit_value:,.2f} $"
                if order_type.startswith("POSITION_TYPE_"):
                    match = re.match(r"POSITION_TYPE_(.*)", order_type)
                    if match:
                        simplified_type = match.group(1)
                row = [
                    order_or_position.get("id", ""),
                    simplified_type,
                    order_or_position.get("symbol", ""),
                    order_or_position.get("volume", ""),
                    order_or_position.get("openPrice", ""),
                    order_or_position.get("stopLoss", ""),
                    order_or_position.get("takeProfit", ""),
                    profit_with_currency,
                ]
                total_profit += float(order_or_position.get("profit", 0))
            else:
                order_type = order_or_position.get("type", "")
                if order_type.startswith("ORDER_TYPE_"):
                    match = re.match(r"ORDER_TYPE_(.*)", order_type)
                    if match:
                        simplified_type = match.group(1)
                row = [
                    order_or_position.get("id", ""),
                    simplified_type,
                    order_or_position.get("symbol", ""),
                    order_or_position.get("volume", ""),
                    order_or_position.get("openPrice", ""),
                    order_or_position.get("stopLoss", ""),
                    order_or_position.get("takeProfit", ""),
                ]
            table.add_row(row)
            # Sort the table by the "Profit" column in descending order

        if not is_pending:
            total_profit_row = [
                "TOTAL PROFIT",
                "",
                "",
                "",
                "",
                "",
                "",
                f"{round(total_profit, 2)} $",
            ]
            table.add_row(total_profit_row)
        return table
    except Exception as e:
        # Xử lý lỗi khi có vấn đề với định dạng dữ liệu
        logger.info(f"Error creating table: {e}")
        return None


async def pending_orders(update: Update, context: CallbackContext) -> None:
    try:
        countrow = 0
        pending_orders_data = await get_pending_orders(update)
        table = create_table(pending_orders_data)
        countrow = len(table._rows)
        update.effective_message.reply_text(f"Total Pending Orders: {countrow}")
        batch_size = 30
        # In các phần
        for start in range(0, countrow, batch_size):
            end = min(start + batch_size, countrow)
            temp_table = table.get_string(start=start, end=end)
            part_temp_table = f"<pre>{temp_table}</pre>"
            update.effective_message.reply_text(
                part_temp_table, parse_mode=ParseMode.HTML
            )
    except Exception as e:
        update.effective_message.reply_text(f"Error pending orders: {e}")


async def open_trades(update: Update, context: CallbackContext) -> None:
    try:
        countrow = 0
        open_trades_data = await get_open_trades(update)
        table = create_table(open_trades_data, is_pending=False)
        if len(table._rows) == 1:
            countrow == 0
        else:
            countrow = len(table._rows)
        update.effective_message.reply_text(f"Total Positions: {countrow}")
        batch_size = 30
        # In các phần
        for start in range(0, countrow, batch_size):
            end = min(start + batch_size, countrow)
            temp_table = table.get_string(start=start, end=end)
            part_temp_table = f"<pre>{temp_table}</pre>"
            update.effective_message.reply_text(
                part_temp_table, parse_mode=ParseMode.HTML
            )
    except Exception as e:
        update.effective_message.reply_text(f"Error open trades: {e}")


# Function to handle the /trailingstop command
async def trailing_stop(update: Update, args) -> None:
    # Get the string of position IDs from the command arguments
    if not args:
        update.effective_message.reply_text("Please provide a list of position IDs.")
        return

    # Combine the arguments into a single string, then split it into a list of position IDs
    position_ids = "".join(args).split(",")

    api = MetaApi(API_KEY)
    account = await api.metatrader_account_api.get_account(ACCOUNT_ID)
    initial_state = account.state
    deployed_states = ["DEPLOYING", "DEPLOYED"]

    if initial_state not in deployed_states:
        #  wait until account is deployed and connected to broker
        logger.info("Deploying account")
        await account.deploy()

    logger.info("Waiting for API server to connect to broker ...")
    await account.wait_connected()

    # connect to MetaApi API
    connection = account.get_rpc_connection()
    await connection.connect()
    await connection.wait_synchronized()
    # Process each position ID
    for position_id in position_ids:
        try:
            # Convert position ID to an integer (assuming it's a valid integer)
            intposition_id = str(position_id)

            # Get position information
            position = await connection.get_position(intposition_id)
            # Modify the position with trailing stop parameters

            # Check if stopLoss exists, set to its value or None
            stopLoss = position["stopLoss"] if "stopLoss" in position else None

            # Check if takeProfit exists, set to its value or None
            takeProfit = position["takeProfit"] if "takeProfit" in position else None

            # Modify the position with trailing stop parameters
            await connection.modify_position(
                intposition_id,
                stop_loss=position["openPrice"],  # Set stopLoss to the openPrice
                take_profit=takeProfit,  # Set takeProfit to its existing value or None if it doesn't exist
            )

            update.effective_message.reply_text(
                f"Trailing stop set for position ID ({intposition_id}) - Change SL :  {stopLoss} to Entry: {position['openPrice']}. Successfully"
            )

        except ValueError:
            update.effective_message.reply_text(
                f"Invalid position ID: {intposition_id}. Please provide valid integers."
            )
        except Exception as e:
            update.effective_message.reply_text(
                f"Error TrailingStop Position ID {position_id}: {str(e)}."
            )


async def close_position(update: Update, args) -> None:
    # Get the string of position IDs from the command arguments
    if not args:
        update.effective_message.reply_text("Please provide a list of position IDs.")
        return
    # Lấy chuỗi từ args
    command_str = args
    # Tách chuỗi thành danh sách các ID, tách bởi dấu phẩy
    position_ids = command_str.split(",")
    if not position_ids:
        update.effective_message.reply_text("Please provide a list of position IDs.")
        return

    api = MetaApi(API_KEY)
    account = await api.metatrader_account_api.get_account(ACCOUNT_ID)
    initial_state = account.state
    deployed_states = ["DEPLOYING", "DEPLOYED"]

    if initial_state not in deployed_states:
        # Wait until account is deployed and connected to the broker
        logger.info("Deploying account")
        await account.deploy()

    logger.info("Waiting for API server to connect to the broker ...")
    await account.wait_connected()

    # Connect to MetaApi API
    connection = account.get_rpc_connection()
    await connection.connect()
    await connection.wait_synchronized()

    # Process each position ID
    for position_id in position_ids:
        try:
            # Close position
            await connection.close_position(position_id)
            update.effective_message.reply_text(
                f"Closed Position ID {position_id} successfully."
            )

        except ValueError:
            update.effective_message.reply_text(
                f"Invalid Position ID: {position_id}. Please provide valid integers."
            )
        except Exception as e:
            update.effective_message.reply_text(
                f"Error closing Position ID {position_id}: {str(e)}."
            )


async def close_position_partially(update: Update, args) -> None:
    # Get the string of position IDs and sizes from the command arguments
    if not args or "|" not in args:
        update.effective_message.reply_text(
            "Please provide a list of position IDs and sizes separated by '|'."
        )
        return

    # Split the arguments into position IDs and sizes
    position_args = args.split("|")
    listID = position_args[0].split(",")
    # listID_str = ', '.join(map(str, listID))
    # update.effective_message.reply_text(f"List ID: {listID_str}.")
    listSize = list(map(float, position_args[1].split(",")))
    api = MetaApi(API_KEY)
    account = await api.metatrader_account_api.get_account(ACCOUNT_ID)
    initial_state = account.state
    deployed_states = ["DEPLOYING", "DEPLOYED"]

    if initial_state not in deployed_states:
        #  wait until account is deployed and connected to broker
        logger.info("Deploying account")
        await account.deploy()

    logger.info("Waiting for API server to connect to broker ...")
    await account.wait_connected()

    # connect to MetaApi API
    connection = account.get_rpc_connection()
    await connection.connect()
    await connection.wait_synchronized()
    # Process each position ID and size
    for i, position_id in enumerate(listID):
        try:
            # Kiểm tra nếu không tồn tại phần tử tương ứng trong listSize
            if i >= len(listSize):
                update.effective_message.reply_text(
                    f"No size provided for Position ID {position_id}."
                )
                break

            size = float(listSize[i])

            # Close a part of the position
            await connection.close_position_partially(position_id, size)

            update.effective_message.reply_text(
                f"Closed a part : {size} lot of Position ID : {position_id} successfully."
            )
        except ValueError:
            update.effective_message.reply_text(
                f"Invalid Position ID: {position_id}. Please provide valid integers."
            )
        except Exception as e:
            update.effective_message.reply_text(
                f"Error closing Position ID {position_id}: {str(e)}."
            )


async def account_info(update: Update) -> None:
    try:
        # Đoạn mã JSON của bạn
        api = MetaApi(API_KEY)
        account = await api.metatrader_account_api.get_account(ACCOUNT_ID)
        initial_state = account.state
        deployed_states = ["DEPLOYING", "DEPLOYED"]

        if initial_state not in deployed_states:
            #  wait until account is deployed and connected to broker
            logger.info("Deploying account")
            await account.deploy()

        logger.info("Waiting for API server to connect to broker ...")
        await account.wait_connected()

        # connect to MetaApi API
        connection = account.get_rpc_connection()
        await connection.connect()
        await connection.wait_synchronized()
        account_information = await connection.get_account_information()
        logger.info(f"Account Info : {account_information}")
        # Tạo PrettyTable
        table = PrettyTable(["Title", "Value"])
        table.align["Title"] = "l"
        table.align["Value"] = "l"
        # Thêm dữ liệu vào PrettyTable
        # Chọn các trường bạn muốn hiển thị
        fields_to_display = [
            "balance",
            "equity",
            "margin",
            "freeMargin",
            "leverage",
            "marginLevel",
        ]

        # Thêm dữ liệu vào PrettyTable
        for field in fields_to_display:
            # Chuyển đổi tên trường thành tiếng Việt
            field_name_vietnamese = {
                "balance": "Balance - Số dư",
                "equity": "Equity - Tài sản ròng",
                "margin": "Margin - Tiền ký quỹ",
                "freeMargin": "FreeMargin - Số dư margin",
                "leverage": "Leverage - Đòn bẩy",
                "marginLevel": "Margin Level - % ký quỹ",
            }.get(field, field)
            if field in ["balance", "equity", "margin", "freeMargin"]:
                field_value = "$ {:,.2f}".format(account_information.get(field, 0))
            elif field == "marginLevel":
                field_value = "{:.2f} %".format(account_information.get(field, 0))
            else:
                field_value = account_information.get(field, 0)
            table.add_row([field_name_vietnamese, field_value])
        # Gửi bảng dưới dạng tin nhắn HTML
        temp_table = f"<pre>{table}</pre>"
        update.effective_message.reply_text(
            f"<pre>{temp_table}</pre>", parse_mode=ParseMode.HTML
            )
    except Exception as e:
        update.effective_message.reply_text(f"Error get Account Infomation: {str(e)}.")

    def ButtonMenu(update, context):
        """
        Button Callback Handler

        This function handles button callbacks and sends a message based on the button pressed.

        Args:
        update (telegram.Update): The update object containing information about the incoming message.
        context (telegram.ext.CallbackContext): The context object for the bot.

        Returns:
        None
        """
        query = update.callback_query
        if query.data == "button1":
            query.edit_message_text(text="You pressed Button 1!")
        elif query.data == "button2":
            query.edit_message_text(text="You pressed Button 2!")
        elif query.data == "button3":
            query.edit_message_text(text="You pressed Button 2!")


def handle_account_info(update: Update, context: CallbackContext):
    asyncio.run(account_info(update))


def handle_pending_orders(update: Update, context: CallbackContext):
    asyncio.run(pending_orders(update, context))


def handle_open_trades(update: Update, context: CallbackContext):
    asyncio.run(open_trades(update, context))


def handle_trailingstop(update: Update, context: CallbackContext):
    args = update.effective_message.text.split(" ")[1:]
    asyncio.run(trailing_stop(update, args[0]))


def handle_closeposition(update: Update, context: CallbackContext):
    args = update.effective_message.text.split(" ")[1:]
    asyncio.run(close_position(update, args[0]))


def handle_close_position_part(update: Update, context: CallbackContext):
    args = update.effective_message.text.split(" ")[1:]
    asyncio.run(close_position_partially(update, args[0]))


# def find_entry_point(trade: str, signal: list[str], signaltype : str) -> float:
#     first_line_with_order_type = next((i for i in range(len(signal)) if signal[i].upper().find(order_type_to_find, 0) != -1), -1)


#     try:
#         entry_price = float(re.split('[a-z]+|[-,/,@]', signal[first_line_with_order_type], flags=re.IGNORECASE)[-1])
#     except ValueError:
#         entry_price = None
#     return entry_price
def replace_spaces(text):
    """
    Thay thế khoảng trắng nằm giữa 2 số thành dấu .

    Args:
      text: Chuỗi cần xử lý

    Returns:
      Chuỗi đã được xử lý
    """
    temp = re.sub(r"(\d+) +(\d+)(?!0)", r"\1.\2", text)
    return temp


def ParseSignal(signal: str) -> dict:
    """Starts process of parsing signal and entering trade on MetaTrader account.

    Arguments:
        signal: trading signal

    Returns:
        a dictionary that contains trade signal information
    """

    # converts message to list of strings for parsing
    signal = remove_pips(signal)
    signal = replace_spaces(signal)
    signal = signal.splitlines()
    signal = [line.rstrip() for line in signal]

    # signalstripemty = [x.strip(' ') for x in signal]

    trade = {}

    # determines the order type of the trade
    if (
        "Buy Limit".lower() in signal[0].lower()
        or "Buy Limit".lower() in signal[1].lower()
        or "Buy Limit".lower() in signal[2].lower()
    ):
        trade["OrderType"] = "Buy Limit"

    elif (
        "Sell Limit".lower() in signal[0].lower()
        or "Sell Limit".lower() in signal[1].lower()
        or "Sell Limit".lower() in signal[2].lower()
    ):
        trade["OrderType"] = "Sell Limit"

    elif (
        "Buy Stop".lower() in signal[0].lower()
        or "Buy Stop".lower() in signal[1].lower()
        or "Buy Stop".lower() in signal[2].lower()
    ):
        trade["OrderType"] = "Buy Stop"

    elif (
        "Sell Stop".lower() in signal[0].lower()
        or "Sell Stop".lower() in signal[1].lower()
        or "Sell Stop".lower() in signal[2].lower()
    ):
        trade["OrderType"] = "Sell Stop"

    elif (
        "Buy Now".lower() in signal[0].lower()
        or "Buy Now".lower() in signal[1].lower()
        or "Buy Now".lower() in signal[2].lower()
    ):
        trade["OrderType"] = "Buy Now"

    elif (
        "Sell Now".lower() in signal[0].lower()
        or "Sell Now".lower() in signal[1].lower()
        or "Sell Now".lower() in signal[2].lower()
    ):
        trade["OrderType"] = "Sell Now"

    elif (
        "Buy".lower() in signal[0].lower()
        or "Buy".lower() in signal[1].lower()
        or "Buy".lower() in signal[2].lower()
    ):
        trade["OrderType"] = "Buy"

    elif (
        "Sell".lower() in signal[0].lower()
        or "Sell".lower() in signal[1].lower()
        or "Sell".lower() in signal[2].lower()
    ):
        trade["OrderType"] = "Sell"

    # returns an empty dictionary if an invalid order type was given
    else:
        return {}

    # extracts symbolplus '/' from trade signal if found then replace '/' to ''
    symbolflag = 0
    for elemental in SYMBOLSPLUS:
        calcusymbol = signal[0].upper().find(elemental, 0)
        if calcusymbol != -1:
            trade["Symbol"] = elemental.replace("/", "")
            symbolflag = 1

    # extracts symbol from trade signal
    if symbolflag == 0:
        for element in SYMBOLS:
            calcu = signal[0].upper().find(element, 0)
            if calcu != -1:
                trade["Symbol"] = element

    # checks if the symbol is valid, if not, returns an empty dictionary
    if trade["Symbol"] not in SYMBOLS:
        return {}

    # change symbol trade signal
    if trade["Symbol"] == "GOLD":
        trade["Symbol"] = "XAUUSD"
    elif trade["Symbol"] == "NAS100":
        trade["Symbol"] = "USTEC"

    # Find symbol 'Entry' if found 'entry' will get float entry in Signal and specical Entry = NOW
    entrygetbuy = FindTP("ENTRY", signal)
    flagbuyentry = 0
    if len(entrygetbuy) > 0:
        trade["Entry"] = float(entrygetbuy[0])
        flagbuyentry = 1

    # checks entry for 'BUY'/'SELL' OrderType
    if (
        trade["OrderType"] == "Buy" or trade["OrderType"] == "Sell"
    ) and flagbuyentry == 0:
        memforfindorderentry = trade["OrderType"].upper()
        for i in range(len(signal)):
            if signal[i] != "":
                j = signal[i].upper().find(memforfindorderentry, 0)
                if j != -1 and i == 0:
                    getentryfirstline = re.split(
                        "[a-z]+|[-,/,@]", signal[i], flags=re.IGNORECASE
                    )[-1]
                    if getentryfirstline != "":
                        trade["Entry"] = float(getentryfirstline)
                    else:
                        trade["Entry"] = ""
                elif j != -1 and i > 0:
                    getentrybyline = re.split(
                        "[a-z]+|[-,/,@]", signal[i], flags=re.IGNORECASE
                    )[-1]
                    if getentrybyline != "":
                        trade["Entry"] = float(getentrybyline)
                    else:
                        trade["Entry"] = ""
    # checks wheter or not to convert entry to float because of market exectution option ("NOW")
    if (
        trade["OrderType"] == "Buy Limit" or trade["OrderType"] == "Sell Limit"
    ) and flagbuyentry == 0:
        oneline = re.split("[a-z]+|[-,/,@]", signal[0], flags=re.IGNORECASE)[-1]
        if oneline != "":
            trade["Entry"] = float(oneline)

        elif oneline == "" and signal[1] != "":
            trade["Entry"] = float((signal[1].split())[-1])

        else:
            trade["Entry"] = float((signal[2].split())[-1])

    # checks wheter or not to convert entry to float because of market exectution option ("NOW")
    if trade["OrderType"] == "Buy Now" or trade["OrderType"] == "Sell Now":
        trade["Entry"] = "NOW"

    # Change symbol ordertype from buy/sell to buy limit/sell limit with if : trade['Entry'] != NOW
    if trade["OrderType"] == "Buy" and trade["Entry"] != "NOW" and trade["Entry"] != "":
        trade["OrderType"] = "Buy Limit"
    elif (
        trade["OrderType"] == "Sell"
        and trade["Entry"] != "NOW"
        and trade["Entry"] != ""
    ):
        trade["OrderType"] = "Sell Limit"
    elif (
        trade["OrderType"] == "Buy" and trade["Entry"] != "NOW" and trade["Entry"] == ""
    ):
        trade["Entry"] = "NOW"
    elif (
        trade["OrderType"] == "Sell"
        and trade["Entry"] != "NOW"
        and trade["Entry"] == ""
    ):
        trade["Entry"] = "NOW"

    # find and add TP
    arraytp = FindTP("TP", signal)
    arraytarget = FindTP("Target Profit", signal)
    if len(arraytp) > 0:
        trade["TP"] = arraytp
    elif len(arraytarget) > 0 and len(arraytp) == 0:
        trade["TP"] = arraytarget
    else:
        trade["TP"] = [float((signal[3].split())[-1])]

    # find and add SL
    stoplosser = FindTP("SL", signal)
    stoplosserb = FindTP("STOP LOSS", signal)
    if len(stoplosser) > 0:
        trade["StopLoss"] = float(stoplosser[0])
    elif len(stoplosserb) > 0 and len(stoplosser) == 0:
        trade["StopLoss"] = float(stoplosserb[0])
    else:
        trade["StopLoss"] = float((signal[2].split())[-1])

    # adds risk factor to trade
    trade["RiskFactor"] = RISK_FACTOR
    trade["RiskPerTrade"] = RISK_PERTRADE

    return trade


def GetTradeInformation(update: Update, trade: dict, balance: float) -> None:
    """Calculates information from given trade including stop loss and take profit in pips, posiition size, and potential loss/profit.

    Arguments:
        update: update from Telegram
        trade: dictionary that stores trade information
        balance: current balance of the MetaTrader account
    """
    try:
        default_multiplier = 0.0001
        # calculates the stop loss in pips
        if trade["Symbol"] == "XAUUSD":
            multiplier = 0.1

        elif trade["Symbol"] == "XAGUSD":
            multiplier = 0.001

        elif trade["Symbol"] in ["US30", "US500", "USTEC", "NAS100"]:
            multiplier = 0.1
        elif str(trade["Entry"]).index(".") >= 2:
            multiplier = 0.01
        else:
            multiplier = 0.0001

        # calculates the stop loss in pips
        stopLossPips = abs(round((trade["StopLoss"] - trade["Entry"]) / multiplier))

        # calculates the take profit(s) in pips
        takeProfitPips = []
        for takeProfit in trade["TP"]:
            takeProfitPips.append(
                abs(round((takeProfit - trade["Entry"]) / multiplier))
            )
        tradeTP = []
        for takeProfit in trade["TP"]:
            tradeTP.append(takeProfit)

        if PLAN == "A":
            # calculates the position size using stop loss and RISK FACTOR
            trade["PositionSize"] = (
                math.floor(((balance * trade["RiskFactor"]) / stopLossPips) / 10 * 100)
                / 100
            )
        elif PLAN == "B":
            # calculates the position size using stop loss and RISK FACTOR
            rr_coefficient = calculate_rr_coefficient(takeProfitPips, stopLossPips)
            positionSize = []
            rickandreward = []
            for rr in rr_coefficient:
                position_size = (
                    math.floor(
                        ((balance * trade["RiskPerTrade"] * rr) / stopLossPips)
                        / 10
                        * 100
                    )
                    / 100
                )
                positionSize.append(position_size)
                rickandreward.append(rr)
            trade["RR"] = rickandreward
            trade["PositionSize"] = positionSize
        # creates table with trade information
        table = CreateTable(trade, balance, stopLossPips, takeProfitPips, tradeTP)

        # sends user trade information and calcualted risk
        update.effective_message.reply_text(
            f"<pre>{table}</pre>", parse_mode=ParseMode.HTML
        )

    except Exception as error:
        logger.error(f"Error Trade: {error}")
        update.effective_message.reply_text(
            f"There was an issue with the connection 😕\n\nError Message:\n{error}"
        )

    return


def CreateTable(
    trade: dict, balance: float, stopLossPips: int, takeProfitPips: int, tradeTP: float
) -> PrettyTable:
    """Creates PrettyTable object to display trade information to user.

    Arguments:
        trade: dictionary that stores trade information
        balance: current balance of the MetaTrader account
        stopLossPips: the difference in pips from stop loss price to entry price

    Returns:
        a Pretty Table object that contains trade information
    """
    if PLAN == "A":
        # creates prettytable object
        table = PrettyTable()
        table.title = "Trade InformationAI - Risk Position Size"
        table.field_names = ["Key", "Value"]
        table.align["Key"] = "l"
        table.align["Value"] = "l"

        table.add_row([trade["OrderType"], trade["Symbol"]])
        table.add_row(["Entry\n", trade["Entry"]])

        table.add_row(["Stop Loss", "{} pips".format(stopLossPips)])

        for count, takeProfit in enumerate(takeProfitPips):
            table.add_row([f"TP {count + 1}", f"({takeProfit} pips)"])
        table.add_row(["\n", ""])
        table.add_row(["Stop Loss", trade["StopLoss"]])
        for count, tradeTPflt in enumerate(tradeTP):
            table.add_row([f"TP {count + 1}", f"{tradeTPflt}"])

        table.add_row(
            ["\nRisk Factor", "\n{:,.0f} %".format(trade["RiskFactor"] * 100)]
        )
        table.add_row(["Position Size", trade["PositionSize"]])

        table.add_row(["\nCurrent Balance", "\n$ {:,.2f}".format(balance)])
        table.add_row(
            [
                "Potential Loss",
                "$ {:,.2f}".format(
                    round((trade["PositionSize"] * 10) * stopLossPips, 2)
                ),
            ]
        )

        # total potential profit from trade
        totalProfit = 0

        for count, takeProfit in enumerate(takeProfitPips):
            profit = round(
                (trade["PositionSize"] * 10 * (1 / len(takeProfitPips))) * takeProfit, 2
            )
            table.add_row([f"TP {count + 1} Profit", "$ {:,.2f}".format(profit)])

            # sums potential profit from each take profit target
            totalProfit += profit

        table.add_row(["\nTotal Profit", "\n$ {:,.2f}".format(totalProfit)])
    elif PLAN == "B":
        # creates prettytable object
        table = PrettyTable()
        table.title = "Trade Information AI - R:R Kelly Criterion"
        table.field_names = ["Key", "Value"]
        table.align["Key"] = "l"
        table.align["Value"] = "l"

        table.add_row([trade["OrderType"], trade["Symbol"]])
        table.add_row(["Entry\n", trade["Entry"]])

        table.add_row(["Stop Loss", "{} pips".format(stopLossPips)])
        positionSize = trade["PositionSize"]

        for count, takeProfit in enumerate(takeProfitPips):
            table.add_row([f"TP {count + 1}", f"({takeProfit} pips)"])
        table.add_row(["\n", ""])
        table.add_row(["Stop Loss", trade["StopLoss"]])
        for count, tradeTPflt in enumerate(tradeTP):
            table.add_row([f"TP {count + 1}", f"{tradeTPflt}"])

        table.add_row(
            ["\nRiskPerTrade", "\n{:,.0f} %".format(trade["RiskPerTrade"] * 100)]
        )

        for count, position_size in enumerate(positionSize):
            if isinstance(position_size, (int, float)):
                rounded_position_size = round(position_size, 2)
                table.add_row([f"Position Size {count + 1}", rounded_position_size])
            else:
                print(f"Skipping non-numeric value at index {count}")
        # total potential loss from trade
        totalLoss = 0

        table.add_row(["\nCurrent Balance", "\n$ {:,.2f}".format(balance)])
        for count, position_size in enumerate(positionSize):
            if isinstance(position_size, (int, float)):
                potential_loss = round((position_size * 10) * stopLossPips, 2)
                table.add_row(
                    [f"Potential Loss {count + 1}", "$ {:,.2f}".format(potential_loss)]
                )
                totalLoss += potential_loss
            else:
                print(f"Skipping non-numeric value at index {count}")
        # total potential profit from trade
        totalProfit = 0

        for count, takeProfit in enumerate(takeProfitPips):
            position_sizes = positionSize[count]
            # Retrieve the corresponding position size for the current take profit level
            # position_sz = trade['PositionSize'][count]
            profit = round(position_size * 10 * takeProfit, 2)
            table.add_row([f"TP {count + 1} Profit", "$ {:,.2f}".format(profit)])

            # sums potential profit from each take profit target
            totalProfit += profit
        table.add_row(["\nTotal Loss", "\n$ {:,.2f}".format(totalLoss)])
        table.add_row(["Total Profit", "$ {:,.2f}".format(totalProfit)])
    return table


async def ConnectMetaTrader(update: Update, trade: dict, enterTrade: bool):
    """Attempts connection to MetaAPI and MetaTrader to place trade.

    Arguments:
        update: update from Telegram
        trade: dictionary that stores trade information

    Returns:
        A coroutine that confirms that the connection to MetaAPI/MetaTrader and trade placement were successful
    """

    # creates connection to MetaAPI
    api = MetaApi(API_KEY)

    try:
        account = await api.metatrader_account_api.get_account(ACCOUNT_ID)
        initial_state = account.state
        deployed_states = ["DEPLOYING", "DEPLOYED"]

        if initial_state not in deployed_states:
            #  wait until account is deployed and connected to broker
            logger.info("Deploying account")
            await account.deploy()

        logger.info("Waiting for API server to connect to broker ...")
        await account.wait_connected()

        # connect to MetaApi API
        connection = account.get_rpc_connection()
        await connection.connect()

        # wait until terminal state synchronized to the local state
        logger.info("Waiting for SDK to synchronize to terminal state ...")
        await connection.wait_synchronized()

        # obtains account information from MetaTrader server
        account_information = await connection.get_account_information()

        update.effective_message.reply_text(
            "Successfully connected to MetaTrader!\nCalculating trade risk ... 🤔"
        )
        price = await connection.get_symbol_price(symbol=trade["Symbol"])
        # checks if the order is a market execution to get the current price of symbol
        if trade["Entry"] == "NOW":
            # uses ask price if the order type is a buy
            if trade["OrderType"] == "Buy" or trade["OrderType"] == "Buy Now":
                trade["Entry"] = float(price["ask"])

            # uses bid price if the order type is a sell
            if trade["OrderType"] == "Sell" or trade["OrderType"] == "Sell Now":
                trade["Entry"] = float(price["bid"])

        # produces a table with trade information
        # GetTradeInformation(update, trade, account_information['balance'])

        # checks if the user has indicated to enter trade
        if enterTrade == True:
            # enters trade on to MetaTrader account
            update.effective_message.reply_text(
                "Entering trade on MetaTrader Account ... 👨🏾‍💻"
            )

            try:
                # executes buy market execution order
                # Kiểm tra nếu giá hiện tại thấp hơn giá Entry cho lệnh Buy Limit
                if (
                    trade["OrderType"] == "Buy Limit"
                    and float(price["bid"]) < trade["Entry"]
                ):
                    trade["OrderType"] = "Buy Stop"

                # Kiểm tra nếu giá hiện tại cao hơn giá Entry cho lệnh Sell Limit
                elif (
                    trade["OrderType"] == "Sell Limit"
                    and float(price["ask"]) > trade["Entry"]
                ):
                    trade["OrderType"] = "Sell Stop"

                # GET INFOMATION TRADE - CREATE TABLE TRADE
                # produces a table with trade information
                GetTradeInformation(update, trade, account_information["balance"])

                if PLAN == "A":
                    # Kiểm tra nếu trailing stop được kích hoạt và có ít nhất 2 TP
                    if TRAILINGSTOP == "Y" and len(trade["TP"]) >= 2:
                        entryTrade = float(trade["Entry"])
                        tradeFirstTP = float(trade["TP"][0])
                        trailing_stop_config = {
                            "trailingStopLoss": {
                                "threshold": {
                                    "thresholds": [
                                        {
                                            "threshold": tradeFirstTP,
                                            "stopLoss": entryTrade,
                                        }
                                    ],
                                    "units": "ABSOLUTE_PRICE",
                                    "stopPriceBase": "CURRENT_PRICE",
                                }
                            }
                        }

                        threshold_TP1 = trade["Entry"] + (
                            (trade["TP"][0] - trade["Entry"]) * 0.8
                        )
                        # decimal_places_entry = len(str(price['bid']).split('.')[-1]) if '.' in str(price['bid']) else 0
                        decimal_places_entry = 4
                        if decimal_places_entry == 0:
                            threshold_TP1 = round(threshold_TP1)
                        else:
                            threshold_TP1 = round(threshold_TP1, decimal_places_entry)
                        trailing_stop_TP1 = {
                            "trailingStopLoss": {
                                "threshold": {
                                    "thresholds": [
                                        {
                                            "threshold": threshold_TP1,
                                            "stopLoss": entryTrade,
                                        }
                                    ],
                                    "units": "ABSOLUTE_PRICE",
                                    "stopPriceBase": "CURRENT_PRICE",
                                }
                            }
                        }
                        # Tiếp tục thực hiện lệnh tương ứng
                        for i, takeProfit in enumerate(trade["TP"]):
                            if i >= 1:
                                if trade["OrderType"] == "Buy":
                                    result = await connection.create_market_buy_order(
                                        trade["Symbol"],
                                        trade["PositionSize"] / len(trade["TP"]),
                                        trade["StopLoss"],
                                        takeProfit,
                                        trailing_stop_config,
                                    )
                                elif trade["OrderType"] == "Buy Now":
                                    result = await connection.create_market_buy_order(
                                        trade["Symbol"],
                                        trade["PositionSize"] / len(trade["TP"]),
                                        trade["StopLoss"],
                                        takeProfit,
                                        trailing_stop_config,
                                    )
                                elif trade["OrderType"] == "Buy Limit":
                                    result = await connection.create_limit_buy_order(
                                        trade["Symbol"],
                                        trade["PositionSize"] / len(trade["TP"]),
                                        trade["Entry"],
                                        trade["StopLoss"],
                                        takeProfit,
                                        trailing_stop_config,
                                    )
                                elif trade["OrderType"] == "Buy Stop":
                                    result = await connection.create_stop_buy_order(
                                        trade["Symbol"],
                                        trade["PositionSize"] / len(trade["TP"]),
                                        trade["Entry"],
                                        trade["StopLoss"],
                                        takeProfit,
                                        trailing_stop_config,
                                    )
                                elif trade["OrderType"] == "Sell":
                                    result = await connection.create_market_sell_order(
                                        trade["Symbol"],
                                        trade["PositionSize"] / len(trade["TP"]),
                                        trade["StopLoss"],
                                        takeProfit,
                                        trailing_stop_config,
                                    )
                                elif trade["OrderType"] == "Sell Now":
                                    result = await connection.create_market_sell_order(
                                        trade["Symbol"],
                                        trade["PositionSize"] / len(trade["TP"]),
                                        trade["StopLoss"],
                                        takeProfit,
                                        trailing_stop_config,
                                    )
                                elif trade["OrderType"] == "Sell Limit":
                                    result = await connection.create_limit_sell_order(
                                        trade["Symbol"],
                                        trade["PositionSize"] / len(trade["TP"]),
                                        trade["Entry"],
                                        trade["StopLoss"],
                                        takeProfit,
                                        trailing_stop_config,
                                    )
                                elif trade["OrderType"] == "Sell Stop":
                                    result = await connection.create_stop_sell_order(
                                        trade["Symbol"],
                                        trade["PositionSize"] / len(trade["TP"]),
                                        trade["Entry"],
                                        trade["StopLoss"],
                                        takeProfit,
                                        trailing_stop_config,
                                    )
                            else:
                                if trade["OrderType"] == "Buy":
                                    result = await connection.create_market_buy_order(
                                        trade["Symbol"],
                                        trade["PositionSize"] / len(trade["TP"]),
                                        trade["StopLoss"],
                                        takeProfit,
                                        trailing_stop_TP1,
                                    )
                                elif trade["OrderType"] == "Buy Now":
                                    result = await connection.create_market_buy_order(
                                        trade["Symbol"],
                                        trade["PositionSize"] / len(trade["TP"]),
                                        trade["StopLoss"],
                                        takeProfit,
                                        trailing_stop_TP1,
                                    )
                                elif trade["OrderType"] == "Buy Limit":
                                    result = await connection.create_limit_buy_order(
                                        trade["Symbol"],
                                        trade["PositionSize"] / len(trade["TP"]),
                                        trade["Entry"],
                                        trade["StopLoss"],
                                        takeProfit,
                                        trailing_stop_TP1,
                                    )
                                elif trade["OrderType"] == "Buy Stop":
                                    result = await connection.create_stop_buy_order(
                                        trade["Symbol"],
                                        trade["PositionSize"] / len(trade["TP"]),
                                        trade["Entry"],
                                        trade["StopLoss"],
                                        takeProfit,
                                        trailing_stop_TP1,
                                    )
                                elif trade["OrderType"] == "Sell":
                                    result = await connection.create_market_sell_order(
                                        trade["Symbol"],
                                        trade["PositionSize"] / len(trade["TP"]),
                                        trade["StopLoss"],
                                        takeProfit,
                                        trailing_stop_TP1,
                                    )
                                elif trade["OrderType"] == "Sell Now":
                                    result = await connection.create_market_sell_order(
                                        trade["Symbol"],
                                        trade["PositionSize"] / len(trade["TP"]),
                                        trade["StopLoss"],
                                        takeProfit,
                                        trailing_stop_TP1,
                                    )
                                elif trade["OrderType"] == "Sell Limit":
                                    result = await connection.create_limit_sell_order(
                                        trade["Symbol"],
                                        trade["PositionSize"] / len(trade["TP"]),
                                        trade["Entry"],
                                        trade["StopLoss"],
                                        takeProfit,
                                        trailing_stop_TP1,
                                    )
                                elif trade["OrderType"] == "Sell Stop":
                                    result = await connection.create_stop_sell_order(
                                        trade["Symbol"],
                                        trade["PositionSize"] / len(trade["TP"]),
                                        trade["Entry"],
                                        trade["StopLoss"],
                                        takeProfit,
                                        trailing_stop_TP1,
                                    )
                    else:
                        # Tiếp tục thực hiện lệnh tương ứng
                        for takeProfit in trade["TP"]:
                            if trade["OrderType"] == "Buy":
                                result = await connection.create_market_buy_order(
                                    trade["Symbol"],
                                    trade["PositionSize"] / len(trade["TP"]),
                                    trade["StopLoss"],
                                    takeProfit,
                                )
                            elif trade["OrderType"] == "Buy Now":
                                result = await connection.create_market_buy_order(
                                    trade["Symbol"],
                                    trade["PositionSize"] / len(trade["TP"]),
                                    trade["StopLoss"],
                                    takeProfit,
                                )
                            elif trade["OrderType"] == "Buy Limit":
                                result = await connection.create_limit_buy_order(
                                    trade["Symbol"],
                                    trade["PositionSize"] / len(trade["TP"]),
                                    trade["Entry"],
                                    trade["StopLoss"],
                                    takeProfit,
                                )
                            elif trade["OrderType"] == "Buy Stop":
                                result = await connection.create_stop_buy_order(
                                    trade["Symbol"],
                                    trade["PositionSize"] / len(trade["TP"]),
                                    trade["Entry"],
                                    trade["StopLoss"],
                                    takeProfit,
                                )
                            elif trade["OrderType"] == "Sell":
                                result = await connection.create_market_sell_order(
                                    trade["Symbol"],
                                    trade["PositionSize"] / len(trade["TP"]),
                                    trade["StopLoss"],
                                    takeProfit,
                                )
                            elif trade["OrderType"] == "Sell Now":
                                result = await connection.create_market_sell_order(
                                    trade["Symbol"],
                                    trade["PositionSize"] / len(trade["TP"]),
                                    trade["StopLoss"],
                                    takeProfit,
                                )
                            elif trade["OrderType"] == "Sell Limit":
                                result = await connection.create_limit_sell_order(
                                    trade["Symbol"],
                                    trade["PositionSize"] / len(trade["TP"]),
                                    trade["Entry"],
                                    trade["StopLoss"],
                                    takeProfit,
                                )
                            elif trade["OrderType"] == "Sell Stop":
                                result = await connection.create_stop_sell_order(
                                    trade["Symbol"],
                                    trade["PositionSize"] / len(trade["TP"]),
                                    trade["Entry"],
                                    trade["StopLoss"],
                                    takeProfit,
                                )
                elif PLAN == "B":
                    if TRAILINGSTOP == "Y" and len(trade["TP"]) >= 2:
                        entryTrade = float(trade["Entry"])
                        tradeFirstTP = float(trade["TP"][0])
                        trailing_stop_config = {
                            "trailingStopLoss": {
                                "threshold": {
                                    "thresholds": [
                                        {
                                            "threshold": tradeFirstTP,
                                            "stopLoss": entryTrade,
                                        }
                                    ],
                                    "units": "ABSOLUTE_PRICE",
                                    "stopPriceBase": "CURRENT_PRICE",
                                }
                            }
                        }

                        threshold_TP1 = trade["Entry"] + (
                            (trade["TP"][0] - trade["Entry"]) * 0.8
                        )
                        # decimal_places_entry = len(str(price['bid']).split('.')[-1]) if '.' in str(price['bid']) else 0
                        decimal_places_entry = 4
                        if decimal_places_entry == 0:
                            threshold_TP1 = round(threshold_TP1, 4)
                        else:
                            threshold_TP1 = round(threshold_TP1, decimal_places_entry)
                        trailing_stop_TP1 = {
                            "trailingStopLoss": {
                                "threshold": {
                                    "thresholds": [
                                        {
                                            "threshold": threshold_TP1,
                                            "stopLoss": entryTrade,
                                        }
                                    ],
                                    "units": "ABSOLUTE_PRICE",
                                    "stopPriceBase": "CURRENT_PRICE",
                                }
                            }
                        }
                        for i, takeProfit in enumerate(trade["TP"]):
                            if i >= 1:
                                if trade["OrderType"] == "Buy":
                                    result = await connection.create_market_buy_order(
                                        trade["Symbol"],
                                        trade["PositionSize"] / len(trade["TP"]),
                                        trade["StopLoss"],
                                        takeProfit,
                                        trailing_stop_config,
                                    )
                                elif trade["OrderType"] == "Buy Now":
                                    result = await connection.create_market_buy_order(
                                        trade["Symbol"],
                                        trade["PositionSize"] / len(trade["TP"]),
                                        trade["StopLoss"],
                                        takeProfit,
                                        trailing_stop_config,
                                    )
                                elif trade["OrderType"] == "Buy Limit":
                                    result = await connection.create_limit_buy_order(
                                        trade["Symbol"],
                                        trade["PositionSize"] / len(trade["TP"]),
                                        trade["Entry"],
                                        trade["StopLoss"],
                                        takeProfit,
                                        trailing_stop_config,
                                    )
                                elif trade["OrderType"] == "Buy Stop":
                                    result = await connection.create_stop_buy_order(
                                        trade["Symbol"],
                                        trade["PositionSize"] / len(trade["TP"]),
                                        trade["Entry"],
                                        trade["StopLoss"],
                                        takeProfit,
                                        trailing_stop_config,
                                    )
                                elif trade["OrderType"] == "Sell":
                                    result = await connection.create_market_sell_order(
                                        trade["Symbol"],
                                        trade["PositionSize"] / len(trade["TP"]),
                                        trade["StopLoss"],
                                        takeProfit,
                                        trailing_stop_config,
                                    )
                                elif trade["OrderType"] == "Sell Now":
                                    result = await connection.create_market_sell_order(
                                        trade["Symbol"],
                                        trade["PositionSize"] / len(trade["TP"]),
                                        trade["StopLoss"],
                                        takeProfit,
                                        trailing_stop_config,
                                    )
                                elif trade["OrderType"] == "Sell Limit":
                                    result = await connection.create_limit_sell_order(
                                        trade["Symbol"],
                                        trade["PositionSize"] / len(trade["TP"]),
                                        trade["Entry"],
                                        trade["StopLoss"],
                                        takeProfit,
                                        trailing_stop_config,
                                    )
                                elif trade["OrderType"] == "Sell Stop":
                                    result = await connection.create_stop_sell_order(
                                        trade["Symbol"],
                                        trade["PositionSize"] / len(trade["TP"]),
                                        trade["Entry"],
                                        trade["StopLoss"],
                                        takeProfit,
                                        trailing_stop_config,
                                    )
                            else:
                                if trade["OrderType"] == "Buy":
                                    result = await connection.create_market_buy_order(
                                        trade["Symbol"],
                                        trade["PositionSize"] / len(trade["TP"]),
                                        trade["StopLoss"],
                                        takeProfit,
                                        trailing_stop_TP1,
                                    )
                                elif trade["OrderType"] == "Buy Now":
                                    result = await connection.create_market_buy_order(
                                        trade["Symbol"],
                                        trade["PositionSize"] / len(trade["TP"]),
                                        trade["StopLoss"],
                                        takeProfit,
                                        trailing_stop_TP1,
                                    )
                                elif trade["OrderType"] == "Buy Limit":
                                    result = await connection.create_limit_buy_order(
                                        trade["Symbol"],
                                        trade["PositionSize"] / len(trade["TP"]),
                                        trade["Entry"],
                                        trade["StopLoss"],
                                        takeProfit,
                                        trailing_stop_TP1,
                                    )
                                elif trade["OrderType"] == "Buy Stop":
                                    result = await connection.create_stop_buy_order(
                                        trade["Symbol"],
                                        trade["PositionSize"] / len(trade["TP"]),
                                        trade["Entry"],
                                        trade["StopLoss"],
                                        takeProfit,
                                        trailing_stop_TP1,
                                    )
                                elif trade["OrderType"] == "Sell":
                                    result = await connection.create_market_sell_order(
                                        trade["Symbol"],
                                        trade["PositionSize"] / len(trade["TP"]),
                                        trade["StopLoss"],
                                        takeProfit,
                                        trailing_stop_TP1,
                                    )
                                elif trade["OrderType"] == "Sell Now":
                                    result = await connection.create_market_sell_order(
                                        trade["Symbol"],
                                        trade["PositionSize"] / len(trade["TP"]),
                                        trade["StopLoss"],
                                        takeProfit,
                                        trailing_stop_TP1,
                                    )
                                elif trade["OrderType"] == "Sell Limit":
                                    result = await connection.create_limit_sell_order(
                                        trade["Symbol"],
                                        trade["PositionSize"] / len(trade["TP"]),
                                        trade["Entry"],
                                        trade["StopLoss"],
                                        takeProfit,
                                        trailing_stop_TP1,
                                    )
                                elif trade["OrderType"] == "Sell Stop":
                                    result = await connection.create_stop_sell_order(
                                        trade["Symbol"],
                                        trade["PositionSize"] / len(trade["TP"]),
                                        trade["Entry"],
                                        trade["StopLoss"],
                                        takeProfit,
                                        trailing_stop_TP1,
                                    )
                    else:
                        for i, take_profit in enumerate(trade["TP"]):
                            position_size = trade["PositionSize"][i]
                            if trade["OrderType"] == "Buy":
                                result = await connection.create_market_buy_order(
                                    trade["Symbol"],
                                    position_size,
                                    trade["StopLoss"],
                                    take_profit,
                                )
                            elif trade["OrderType"] == "Buy Now":
                                result = await connection.create_market_buy_order(
                                    trade["Symbol"],
                                    position_size,
                                    trade["StopLoss"],
                                    take_profit,
                                )
                            elif trade["OrderType"] == "Buy Limit":
                                result = await connection.create_limit_buy_order(
                                    trade["Symbol"],
                                    position_size,
                                    trade["Entry"],
                                    trade["StopLoss"],
                                    take_profit,
                                )
                            elif trade["OrderType"] == "Buy Stop":
                                result = await connection.create_stop_buy_order(
                                    trade["Symbol"],
                                    position_size,
                                    trade["Entry"],
                                    trade["StopLoss"],
                                    take_profit,
                                )
                            elif trade["OrderType"] == "Sell":
                                result = await connection.create_market_sell_order(
                                    trade["Symbol"],
                                    position_size,
                                    trade["StopLoss"],
                                    take_profit,
                                )
                            elif trade["OrderType"] == "Sell Now":
                                result = await connection.create_market_sell_order(
                                    trade["Symbol"],
                                    position_size,
                                    trade["StopLoss"],
                                    take_profit,
                                )
                            elif trade["OrderType"] == "Sell Limit":
                                result = await connection.create_limit_sell_order(
                                    trade["Symbol"],
                                    position_size,
                                    trade["Entry"],
                                    trade["StopLoss"],
                                    take_profit,
                                )
                            elif trade["OrderType"] == "Sell Stop":
                                result = await connection.create_stop_sell_order(
                                    trade["Symbol"],
                                    position_size,
                                    trade["Entry"],
                                    trade["StopLoss"],
                                    take_profit,
                                )
                # sends success message to user
                update.effective_message.reply_text("Trade entered successfully! 💰")

                # prints success message to console
                logger.info("\nTrade entered successfully!")
                logger.info(f"\nResult Code: {result}\n")
            except Exception as errors:
                if errors["stringCode"] == "ERR_NO_ERROR" or errors["numericCode"] == 0:
                    logger.info(f"\nTrade with ERR_NO_ERROR : {errors}\n")
                else:
                    logger.info(f"\nTrade failed with error: {errors}\n")
                    update.effective_message.reply_text(
                        f"There was an issue ConnectMetaTrader-00😕\n\nError Message:\n{errors}"
                    )

    except Exception as error:
        logger.error(f"Error Trade: {error}")
        update.effective_message.reply_text(
            f"There was an issue ConnectMetaTrader 😕\n\nError Message:\n{error}"
        )

    return


# Handler Functions
def PlaceTrade(update: Update, context: CallbackContext) -> int:
    """Parses trade and places on MetaTrader account.

    Arguments:
        update: update from Telegram
        context: CallbackContext object that stores commonly used objects in handler callbacks
    """
    # checks if the trade has already been parsed or not
    # if(context.user_data['trade'] is None):

    try:
        # parses signal from Telegram message
        # errorMessage1 = f"There was \nError: {update.effective_message.text}\n."
        # update.effective_message.reply_text(errorMessage1)
        trade = ParseSignal(update.effective_message.text)
        # update.effective_message.reply_text(trade)

        # Test Done OK Here

        # checks if there was an issue with parsing the trade
        if not (trade):
            raise Exception("Invalid Trade")

        # sets the user context trade equal to the parsed trade
        # Fixing here
        # context.user_data['trade'] = trade

        update.effective_message.reply_text(
            "Trade Successfully Parsed! 🥳\nConnecting to MetaTrader ... \n(May take a while) ⏰"
        )

    except Exception as error:
        logger.error(f"Error: {error}")
        errorMessage = f"There was an error parsing this trade 😕\n\nError: {error}\n"
        update.effective_message.reply_text(errorMessage)

        # returns to TRADE state to reattempt trade parsing
        return TRADE

    # attempts connection to MetaTrader and places trade
    asyncio.run(ConnectMetaTrader(update, trade, True))

    # removes trade from user context data
    # context.user_data['trade'] = None

    return TRADE


def CalculateTrade(update: Update, context: CallbackContext) -> int:
    """Parses trade and places on MetaTrader account.

    Arguments:
        update: update from Telegram
        context: CallbackContext object that stores commonly used objects in handler callbacks
    """

    # checks if the trade has already been parsed or not
    if context.user_data["trade"] is None:
        try:
            # parses signal from Telegram message
            trade = ParseSignal(update.effective_message.text)

            # checks if there was an issue with parsing the trade
            if not (trade):
                raise Exception("Invalid Trade")

            # sets the user context trade equal to the parsed trade
            context.user_data["trade"] = trade
            update.effective_message.reply_text(
                "Trade Successfully Parsed! 🥳\nConnecting to MetaTrader ... (May take a while) ⏰"
            )

        except Exception as error:
            logger.error(f"Error CalculateTrade : {error}")
            errorMessage = (
                f"There was an error parsing this trade 😕\n\nError: {error}\n"
            )
            update.effective_message.reply_text(errorMessage)

            # returns to CALCULATE to reattempt trade parsing
            return CALCULATE

    # attempts connection to MetaTrader and calculates trade information
    asyncio.run(ConnectMetaTrader(update, context.user_data["trade"], False))

    # asks if user if they would like to enter or decline trade
    update.effective_message.reply_text(
        "Would you like to enter this trade?\nTo enter, select: /yes\nTo decline, select: /no"
    )

    return DECISION


def unknown_command(update: Update, context: CallbackContext) -> None:
    """Checks if the user is authorized to use this bot or shares to use /help command for instructions.

    Arguments:
        update: update from Telegram
        context: CallbackContext object that stores commonly used objects in handler callbacks
    """
    user_username = update.effective_message.chat.username
    if user_username not in AUTHORIZED_USERS:
        update.effective_message.reply_text(
            "You are not authorized to use this bot! 🙅🏽‍♂️"
        )
        return ConversationHandler.END

    update.effective_message.reply_text(
        "Unknown command. Use /trade to place a trade or /calculate to find information for a trade. You can also use the /help command to view instructions for this bot."
    )

    return


# Command Handlers
def welcome(update: Update, context: CallbackContext) -> None:
    """Sends welcome message to user.

    Arguments:
        update: update from Telegram
        context: CallbackContext object that stores commonly used objects in handler callbacks
    """

    welcome_message = "Welcome to the FX Signal Copier Telegram Bot! 💻💸\n\nYou can use this bot to enter trades directly from Telegram and get a detailed look at your risk to reward ratio with profit, loss, and calculated lot size. You are able to change specific settings such as allowed symbols, risk factor, and more from your personalized Python script and environment variables.\n\nUse the /help command to view instructions and example trades."

    # sends messages to user
    update.effective_message.reply_text(welcome_message)

    return


def help(update: Update, context: CallbackContext) -> None:
    """Sends a help message when the command /help is issued

    Arguments:
        update: update from Telegram
        context: CallbackContext object that stores commonly used objects in handler callbacks
    """

    help_message = "This AI bot is used to automatically enter trades onto your MetaTrader account directly from Telegram. To begin, ensure that you are authorized to use this bot by adjusting your Python script or environment variables.\n\nThis bot supports all trade order types (Market Execution, Limit, and Stop) and many functions : \n    + Check Account Infomation\n    + Check Opening Positions\n    + Pending Orders\n    + Set Trailing Stop\n    + Close All/Close Partially Position\n\n"
    # commands = "List of commands:\n/start : displays welcome message\n/help : displays list of commands and example trades\n/trade : takes in user inputted trade for parsing and placement\n/calculate : calculates trade information for a user inputted trade"
    # trade_example = "Example Trades 💴:\n\n"
    # market_execution_example = "Market Execution:\nBUY GBPUSD\nEntry NOW\nSL 1.14336\nTP 1.28930\nTP 1.29845\n\n"
    # limit_example = "Limit Execution:\nBUY LIMIT GBPUSD\nEntry 1.14480\nSL 1.14336\nTP 1.28930\n\n"
    # note = "You are able to enter up to two take profits. If two are entered, both trades will use half of the position size, and one will use TP1 while the other uses TP2.\n\nNote: Use 'NOW' as the entry to enter a market execution trade."
    commandtrade = "\n----Bot commands:\n\t/accountinfo : Check infomation account\n\t/opentrades : Check all Opening Position\n\t/pendingorders : Check all Pending Orders\n\tcloseposition id,id,id \n\tclosepart id,id|size,size \n\ttrailingstop id,id,id"
    # sends messages to user
    update.effective_message.reply_text(help_message + commandtrade)
    # update.effective_message.reply_text(commands)
    # update.effective_message.reply_text(trade_example + market_execution_example + limit_example + note + commandtrade)
    # update.effective_message.reply_text(commandtrade)
    return


def cancel(update: Update, context: CallbackContext) -> int:
    """Cancels and ends the conversation.

    Arguments:
        update: update from Telegram
        context: CallbackContext object that stores commonly used objects in handler callbacks
    """

    update.effective_message.reply_text("Command has been canceled.")

    # removes trade from user context data
    if context.user_data["trade"] is not None:
        context.user_data["trade"] = None

    return ConversationHandler.END

def error(update: Update, context: CallbackContext) -> None:
    """Logs Errors caused by updates.

    Arguments:
        update: update from Telegram
        context: CallbackContext object that stores commonly used objects in handler callbacks
    """

    logger.warning('Update "%s" caused error "%s"', update, context.error)

    return


def Trade_Command(update: Update, context: CallbackContext) -> int:
    """Asks user to enter the trade they would like to place.

    Arguments:
        update: update from Telegram
        context: CallbackContext object that stores commonly used objects in handler callbacks
    """
    user_username = update.effective_message.chat.username
    if user_username not in AUTHORIZED_USERS:
        update.effective_message.reply_text(
            "You are not authorized to use this bot! 🙅🏽‍♂️"
        )
        return ConversationHandler.END

    # initializes the user's trade as empty prior to input and parsing
    # if context.user_data['trade'] is not None:
    #     context.user_data['trade'] = None

    # asks user to enter the trade
    # update.effective_message.reply_text("Please enter the trade that you would like to place.")

    return TRADE


def Calculation_Command(update: Update, context: CallbackContext) -> int:
    """Asks user to enter the trade they would like to calculate trade information for.

    Arguments:
        update: update from Telegram
        context: CallbackContext object that stores commonly used objects in handler callbacks
    """
    user_username = update.effective_message.chat.username
    if user_username not in AUTHORIZED_USERS:
        update.effective_message.reply_text(
            "You are not authorized to use this bot! 🙅🏽‍♂️"
        )
        return ConversationHandler.END

    # initializes the user's trade as empty prior to input and parsing
    if context.user_data["trade"] is not None:
        context.user_data["trade"] = None

    # asks user to enter the trade
    update.effective_message.reply_text(
        "Please enter the trade that you would like to calculate."
    )

    return CALCULATE


# Function for handle message
def TotalMessHandle(update: Update, context: CallbackContext) -> int:
    checktruesignal = CheckSignalMessage(update.effective_message.text)
    temp = Trade_Command(update, context)
    if temp == TRADE and checktruesignal == TRADE:
        PlaceTrade(update, context)
    return TRADE


# Function for check message is a signal format true
def CheckSignalMessage(signal: str) -> int:
    signal = signal.splitlines()
    signal = [line.rstrip() for line in signal]
    # extracts symbolplus '/' from trade signal if found then replace '/' to ''
    for elemental in SYMBOLSPLUS:
        calcusymbol = signal[0].upper().find(elemental, 0)
        for symbolother in TYPETRADE:
            for item in signal:
                calcusymbolother = item.upper().find(symbolother, 0)
                if calcusymbol != -1 & calcusymbolother != -1:
                    return TRADE
    # extracts symbol from trade signal
    for element in SYMBOLS:
        calcu = signal[0].upper().find(element, 0)
        for symbol_other in TYPETRADE:
            for item in signal:
                calcu_symbolother = item.upper().find(symbol_other, 0)
                if calcu != -1 & calcu_symbolother != -1:
                    return TRADE
    return ERROR


def main() -> None:
    """Runs the Telegram bot."""

    updater = Updater(TOKEN, use_context=True)

    # get the dispatcher to register handlers
    dp = updater.dispatcher

    # message handler
    dp.add_handler(CommandHandler("start", welcome))

    # help command handler
    dp.add_handler(CommandHandler("help", help))

    """conv_handler = ConversationHandler(
        entry_points=[CommandHandler("trade", Trade_Command), CommandHandler("calculate", Calculation_Command)],
        states={
            TRADE: [MessageHandler(Filters.text & ~Filters.command, PlaceTrade)],
            CALCULATE: [MessageHandler(Filters.text & ~Filters.command, CalculateTrade)],
            DECISION: [CommandHandler("yes", PlaceTrade), CommandHandler("no", cancel)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )"""

    # conversation handler for entering trade or calculating trade information
    """dp.add_handler(conv_handler)"""

    pattern_text = rf"^{SELECT_INFO}$|^{SELECT_POSITION}$|^{SELECT_ORDER}$|^{SELECT_TRAILING}$|^{SELECT_CLOSEFULL}$|^{SELECT_CLOSEPART}$"
    pattern_action = rf"^{ACCOUNT_INFO}$|^{OPENING_POSITION}$|^{PENDING_ORDER}$|^{TRAILING_STOP}$|^{CLOSE_POSITION}$|^{CLOSEPART}$"

    # Create the ConversationHandler
    conv_handler_menu = ConversationHandler(
        entry_points=[CommandHandler("menu", menu_button)],
        states={
            SELECT_OPTION: [
                CallbackQueryHandler(select_option, pattern=pattern_text),
            ],
            WAIT_FOR_ID: [MessageHandler(Filters.text & ~Filters.command, handle_ids)],
        },
        fallbacks=[],
        # per_message=True,
    )
    dp.add_handler(conv_handler_menu)

    conv_handler_env = ConversationHandler(
        entry_points=[CommandHandler("updateenv", command_updateenv)],
        states={
            INPUT_TEXT: [MessageHandler(Filters.text & ~Filters.command, update_env)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # message handler for all messages that are not included in conversation handler
    """"dp.add_handler(MessageHandler(Filters.text, unknown_command))"""
    """"dp.add_handler(MessageHandler(Filters.text,TotalMessHandle()))"""
    dp.add_handler(
        MessageHandler(
            Filters.command & Filters.regex("accountinfo"), handle_account_info
        )
    )
    dp.add_handler(
        MessageHandler(
            Filters.command & Filters.regex("pendingorders"), handle_pending_orders
        )
    )
    dp.add_handler(
        MessageHandler(
            Filters.command & Filters.regex("opentrades"), handle_open_trades
        )
    )
    dp.add_handler(
        MessageHandler(
            Filters.command & Filters.regex("trailingstop"), handle_trailingstop
        )
    )
    dp.add_handler(
        MessageHandler(
            Filters.command & Filters.regex("closeposition"), handle_closeposition
        )
    )
    dp.add_handler(
        MessageHandler(
            Filters.command & Filters.regex("closepart"), handle_close_position_part
        )
    )
    dp.add_handler(MessageHandler(Filters.text, TotalMessHandle))

    # log all errors
    dp.add_error_handler(error)

    # listens for incoming updates from Telegram
    updater.start_webhook(
        listen="0.0.0.0", port=PORT, url_path=TOKEN, webhook_url=APP_URL + TOKEN
    )
    updater.idle()

    return


if __name__ == "__main__":
    main()
