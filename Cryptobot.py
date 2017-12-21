import discord
import asyncio
import random
import pickle
import os
import logging
from exchanges.bitfinex import Bitfinex
import coinmarketcap
from tabulate import tabulate
from decimal import Decimal

##------------------------------------- PARAMETERS
discord_bot_token = 'MzkxODE3NjczMzQxNzk2MzYz.DReO0g.qf_wKQ98aopzgcV5QikPm7mEd4o' #replace with your own private key
crypto_ticker_channel_name = "crypto-ticker" #replace with your server's ticker channel name
ticker_update_sec = 900 #seconds between ticker updates
COMMAND_CHARACTER='cb.' #The command prefix that you want 
TICKER_CHARACTER='^' #the ticker prefix that you want
API_PULL_LIMIT = 2000 #the number of API lines to get
TICKER_DISPLAY_LIMIT = 45 #the number of API lines to display (first X by market cap)
VERSION='0.1.0'
RELEASE=True #affects the level of debug output

##------------------------------------- MAIN BOT CODE
#housekeeping globals
crypto_ticker_channel = discord.Object(id='0') #placeholder channel
api_list_all = [] #holds the string list for the ticker table (JSON get format)
on_ready_done = False #global flag for on_ready init done

#enable logging, verbosity depends on if this is a release
if(RELEASE): 
	logging.basicConfig(level=logging.INFO)
	#logging.getLogger("asyncio").setLevel(logging.CRITICAL+1)
else: 
	logging.basicConfig(level=logging.DEBUG)
	logging.getLogger("discord").setLevel(logging.CRITICAL+1)
	logging.getLogger("websockets").setLevel(logging.CRITICAL+1)
	#root_logger.addFilter('root') 

#get a discord client handle (connects to discord server)
client = discord.Client()

##------------------------------------- EVENT: ON_READY()
@client.event
async def on_ready():
	global crypto_ticker_channel
	global on_ready_done

	logging.info('\n----------------------Startup')
	logging.info('Logged in as User %s (%s)',client.user.name, client.user.id)
	logging.info('Connected server/channel list:')

	#print the list of connected servers and their channels (this is informational only)
	server_count=0
	for s in client.servers:
		server_count+=1 #global server count
		channel_count=0 #local count per server
		logging.info('\t[%s]: %s (%s)',server_count, s.name, s.id)
		for c in s.channels:
			channel_count+=1
			logging.info('\t\t[%s]: %s (%s)',channel_count, c.name, c.id)

	#find the first instance of a channel whose name matches the string crypto_ticker_channel_name
	crypto_ticker_channel = discord.utils.find(lambda c: c.name==crypto_ticker_channel_name, s.channels)
	if not crypto_ticker_channel is None: 
		logging.info('\tServer ticker channel found: %s (%s)',crypto_ticker_channel.name, crypto_ticker_channel.id)
	else:
		#if no match found, use the default channel on the first server in the server list 
		for s in client.servers:
			crypto_ticker_channel = s.default_channel
			break
		logging.info('\tNo ticker channel found on any server, using default channel "%s" on server "%s"',crypto_ticker_channel.name, crypto_ticker_channel.server.name)
	#set global flag for init done
	on_ready_done = True
	#do an initial ticker update (the scheduled one won't run because on_ready_done wasn't set at t=0)
	logging.info('\n----------------------End Startup')
	await crypto_ticker_update()

##------------------------------------- EVENT: ON_MESSAGE(message)
@client.event
async def on_message(message):
	message_chunk = message.content.split(" ")
	coin_ref = []

	if(len(message_chunk)==0): return #escape on empty message
	if(message.author==client.user): return #ignore messages coming from CryptoBot (performance)

	command=message_chunk[0]
	#check incoming messages for valid commands
	if(command[:len(COMMAND_CHARACTER)]==COMMAND_CHARACTER):  #starts with valid command code
		logging.debug("command parse: %s | %s", command, command[:len(COMMAND_CHARACTER)])
		if (command[len(COMMAND_CHARACTER):] in on_message_handlers):
			await on_message_handlers[command[len(COMMAND_CHARACTER):]](message) #this actually runs the function from the dictionary, because Python is ridiculous
		else: logging.debug("No handler found for command: %s | %s", command, command[len(COMMAND_CHARACTER):] )  #no handler for the command
	else: #just a normal sentence, or coin references
		for chunk in message_chunk: #iterate through every "word" (seperated by spaces) in the message
			if(len(chunk)==0): continue #skip empty chunks - no one likes empty chunks
			if(chunk[0]==TICKER_CHARACTER): #coin reference
				coin_ref.append(chunk[1:]) #build a list of coin references
		if(len(coin_ref)>0): #someone mentioned a coin
			await print_coin_references(message.channel,coin_ref) # print out a mini-table in the channel where it was mentioned
		else: return #normal message, nothing to do here

##------------------------------------- COMMAND HANDLERS FOR ON_MESSAGE EVENTS

#Command help
async def crypto_bot_help(message):
	logging.debug('crypto_bot_help(%s)',message.content)
	
	display_string="CryptoBot "+VERSION+" command list:\n-------------------------------------\n"
	display_string+=TICKER_CHARACTER+"XXX: get info for a coin whose ticker is XXX (e.g. ^BTC gets Bitcoin).  Multiple tickers may be used per message. Try it out!\n"

	for cmd in on_message_handlers:
		logging.debug("command: %s",cmd)
		display_string+= COMMAND_CHARACTER+cmd+":\t"+on_message_helpstrings[cmd]+"\n"

	await client.send_message(message.channel, "```"+display_string+"```")

#Simple bot status check command
async def crypto_bot_status(message):
	logging.debug('crypto_bot_status(%s)',message.content)
	
	display_string = '```'+'CrytpoBot status is: GOOD'+'```'

	await client.send_message(message.channel, display_string)

# print out a mini-table in the channel where it was mentioned
async def print_coin_references(message_channel,coin_ref,send_lines=15):
	coin_ticker_data=[] # holds the JSON data for the coins referenced

	#get the formatted details for each coin
	for coin_sym in coin_ref:
		result = get_coin_ticker(coin_sym)
		if(result!=None): coin_ticker_data.append(result)
		else: logging.debug("Coin reference %s not found in JSON data", coin_sym) 
	#if no valid references were found, abort without sending any messages
	if(len(coin_ticker_data)==0): return None

	#use tabulate to convert into display friendly table format
	logging.debug('coin_ticker_data: %s', coin_ticker_data)

	coin_ticker_display = tabulate (
		coin_ticker_data, 
		headers=["**Currency**","**Symbol**","**Price(USD)**","**Change(1h)**","**Change(24h)**","**Change(7d)**"],
		tablefmt="simple"
		)

	#print(coin_ticker_display)

	#re-chunk after being formatted back into individual lines
	coin_ticker_buffered = coin_ticker_display.split('\n')

	#print(coin_ticker_buffered)

	#chunk the ticker list into tables that will pass through the 2000 character limit in Discord
	lines=0
	ticker_message=""
	for ticker_line in coin_ticker_buffered:
		if(lines<send_lines): #keep chunking
			ticker_line+='\n' 
			ticker_message+=ticker_line
			lines+=1
		else: #done chunking, send and flush buffer
			#print(ticker_message)
			#prepend and append ``` in order to force Discord to use code block format
			await client.send_message(message_channel, '```'+ticker_message+'```')
			lines=0
			ticker_message=""
	#done chunking but lines might be left in the buffer
	if(lines>0): #lines in buffer
		await client.send_message(message_channel, '```'+ticker_message+'```')
		lines=0
		ticker_message=""

def get_coin_ticker(coin_sym): #return the fields of interest for a single coin reference given by a string, coin_sym
	logging.debug("get_coin_ticker("+coin_sym+")")
	for currency in api_list_all: #iterate through all the JSON data
		if(currency['symbol']==coin_sym): #found a match
			ticker_string = [ 
				currency['name'], 
				currency['symbol'], 
				currency['price_usd'], 
				'{0:+f}'.format(Decimal(currency['percent_change_1h']))+' %',
				'{0:+f}'.format(Decimal(currency['percent_change_24h']))+' %',
				'{0:+f}'.format(Decimal(currency['percent_change_7d']))+' %' 
				]
			logging.debug('ticker_string=%s', ticker_string)
			return ticker_string 
	#we didn't find the ticker in the list
	return None

async def print_full_ticker(send_lines=15,purge=True):
	global api_list_all
	api_list_all_display=[]

	#load just the desired data in the display list
	for currency in api_list_all[0:TICKER_DISPLAY_LIMIT-1+2]: #-1 for index, +2 so that we don't count the header
		api_list_all_display.append(
			[ 
			currency['name'], 
			currency['symbol'], 
			currency['price_usd'], 
			'{0:+f}'.format(Decimal(currency['percent_change_1h']))+' %',
			'{0:+f}'.format(Decimal(currency['percent_change_24h']))+' %',
			'{0:+f}'.format(Decimal(currency['percent_change_7d']))+' %' 
			]
		)

	#use tabulate to convert into display friendly table format.  "```" is for Discord "code block" formatting
	display_string = tabulate (
		api_list_all_display, 
		headers=["**Currency**","**Symbol**","**Price(USD)**","**Change(1h)**","**Change(24h)**","**Change(7d)**"],
		tablefmt="simple"
		)

	#Use split to chunk the table back out into individual strings (for send_message())
	coin_ticker_buffered = display_string.split('\n')

	#purge channel of last 100 CryptoBot messages if option is set
	if(purge): await client.purge_from(crypto_ticker_channel, limit=100, check=lambda m:m.author==client.user)

	#chunk the ticker list into tables that will pass through the 2000 character limit in Discord
	lines=0
	ticker_message=""
	for ticker_line in coin_ticker_buffered:
		if(lines<send_lines): #keep chunking
			ticker_line+='\n' 
			ticker_message+=ticker_line
			lines+=1
		else: #done chunking, send and flush buffer
			#print(ticker_message)
			#prepend and append ``` in order to force Discord to use code block format
			await client.send_message(crypto_ticker_channel, '```'+ticker_message+'```')
			lines=0
			ticker_message=""
	#done chunking but lines might be left in the buffer
	if(lines>0): #lines in buffer
		await client.send_message(crypto_ticker_channel, '```'+ticker_message+'```')
		lines=0
		ticker_message=""

def get_ticker_update():
	global api_list_all
	global api_list_all_chunked

	logging.debug('get_ticker_update()')
	#create new API into coinmarketcap.com
	cmc_api = coinmarketcap.Market()

	#load global variable api_list_all with JSON response
	api_list_all = cmc_api.ticker("",limit=API_PULL_LIMIT,convert='USD') #contains the raw query data from coinmarketcap API

on_message_handlers = { "status" 	: crypto_bot_status,
						"alive" 	: crypto_bot_status,
						"help"		: crypto_bot_help,
						"h"			: crypto_bot_help }

on_message_helpstrings = {  "status" 	: "Displays CryptoBot current status",
							"alive" 	: "Ping Cryptobot to see if it's still running",
							"help"		: "Display this command list",
							"h"			: "Display this command list" }

##------------------------------------- BACKGROUND TASKS (run periodically)
async def crypto_ticker_update():
	await client.wait_until_ready()
	while not client.is_closed: 
		if(on_ready_done): 
			get_ticker_update()
			await print_full_ticker()
		await asyncio.sleep(ticker_update_sec) # schedule task every X sec

##------------------------------------- SCHEDULING BACKGROUND TASKS
client.loop.create_task(crypto_ticker_update())

##------------------------------------- BLOCKING CALL TO RUN BOT
client.run(discord_bot_token)