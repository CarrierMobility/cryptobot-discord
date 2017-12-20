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
COMMAND_CHARACTER='!' #The command prefix that you want 
TICKER_CHARACTER='^' #the ticker prefix that you want
API_PULL_LIMIT = 2000 #the number of API lines to get
TICKER_DISPLAY_LIMIT = 45 #the number of API lines to display (first X by market cap)

##------------------------------------- MAIN BOT CODE
#housekeeping globals
crypto_ticker_channel = discord.Object(id='0') #placeholder channel
api_list_all = [] #holds the string list for the ticker table (JSON get format)
on_ready_done = False #global flag for on_ready init done

#enable logging
logging.basicConfig(level=logging.INFO)
#get a discord client handle (connects to discord server)
client = discord.Client()

##------------------------------------- EVENT: ON_READY()
@client.event
async def on_ready():
	global crypto_ticker_channel
	global on_ready_done

	print('\n-----on_ready-----')
	print('Logged in as User',client.user.name, '(',client.user.id,')')
	print('Connected server/channel list:')

	#print the list of connected servers and their channels (this is informational only)
	server_count=0
	for s in client.servers:
		server_count+=1 #global server count
		channel_count=0 #local count per server
		print('\t[',server_count,']:',s.name,'(',s.id,')')
		for c in s.channels:
			channel_count+=1
			print('\t\t[',channel_count,']:',c.name,'(',c.id,')')

	#find the first instance of a channel whose name matches the string crypto_ticker_channel_name
	crypto_ticker_channel = discord.utils.find(lambda c: c.name==crypto_ticker_channel_name, s.channels)
	if not crypto_ticker_channel is None: 
		print('\tServer ticker channel found: ',crypto_ticker_channel.name,'(',crypto_ticker_channel.id,')')
	else:
		#if no match found, use the default channel on the first server in the server list 
		for s in client.servers:
			crypto_ticker_channel = s.default_channel
			break
		print('\tNo ticker channel found on any server, using default channel "',crypto_ticker_channel.name,'" on server "',crypto_ticker_channel.server.name,'"')
	#set global flag for init done
	on_ready_done = True
	#do an initial ticker update (the scheduled one won't run because on_ready_done wasn't set at t=0)
	await crypto_ticker_update()
	print(on_ready_done)
	print('------------')

##------------------------------------- EVENT: ON_MESSAGE(message)
@client.event
async def on_message(message):
	message_chunk = message.content.split(" ")
	coin_ref = []

	if(len(message_chunk)==0): return #escape on empty message
	if(message.author==client.user): return #ignore messages coming from CryptoBot (performance)

	command=message_chunk[0]
	#check incoming messages for valid commands
	if(command[0]==COMMAND_CHARACTER):  #starts with valid command code
		print("command parse: ", command)
		if (command in on_message_handlers):
			await on_message_handlers[command](message) #this actually runs the function from the dictionary, because Python is ridiculous
		else: print("No handler found for command:", command) #no handler for the command
	else: #just a normal sentence, or coin references
		for chunk in message_chunk: #iterate through every "word" (seperated by spaces) in the message
			if(len(chunk)==0): continue #skip empty chunks - no one likes empty chunks
			if(chunk[0]==TICKER_CHARACTER): #coin reference
				coin_ref.append(chunk[1:]) #build a list of coin references
		if(len(coin_ref)>0): #someone mentioned a coin
			await print_coin_references(message.channel,coin_ref) # print out a mini-table in the channel where it was mentioned
		else: return #normal message, nothing to do here

##------------------------------------- COMMAND HANDLERS FOR ON_MESSAGE EVENTS
async def current_btc_price(message=""):
	global crypto_ticker_channel
	print('ticker_channel: ',crypto_ticker_channel.name)
	#crypto_ticker_channel = discord.utils.find(lambda c: c.name==crypto_ticker_channel_name, message.server.channels)
	ticker_message = "Current BTC Price: $"+ str(Bitfinex().get_current_price())
	await client.send_message(crypto_ticker_channel, ticker_message)

# print out a mini-table in the channel where it was mentioned
async def print_coin_references(message_channel,coin_ref,send_lines=15):
	coin_ticker_data=[] # holds the JSON data for the coins referenced

	#get the formatted details for each coin
	for coin_sym in coin_ref:
		result = get_coin_ticker(coin_sym)
		if(result!=None): coin_ticker_data.append(result)
		else: print("Coin reference",coin_sym,"not found in JSON data") 
	#if no valid references were found, abort without sending any messages
	if(len(coin_ticker_data)==0): return None

	#use tabulate to convert into display friendly table format
	print(coin_ticker_data)
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
	print("get_coin_ticker("+coin_sym+")")
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
			print("ticker_string=",ticker_string)
			return ticker_string 
	#we didn't find the ticker in the list
	return None

async def print_full_ticker(send_lines=15,purge=True):
	global api_list_all
	api_list_all_display=[]

	print("print_full_ticker()")
	#load just the desired data in the display list
	for currency in api_list_all[0:TICKER_DISPLAY_LIMIT-1+2]: #-1 for index, +2 so that we don't count the header
		print(currency['symbol']) #debug
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

	#print(display_string)

	#Use split to chunk the table back out into individual strings (for send_message())
	coin_ticker_buffered = display_string.split('\n')

	#print(display_string_buffered)

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

	print("get_ticker_update()")
	#create new API into coinmarketcap.com
	cmc_api = coinmarketcap.Market()

	#load global variable api_list_all with JSON response
	api_list_all = cmc_api.ticker("",limit=API_PULL_LIMIT,convert='USD') #contains the raw query data from coinmarketcap API

	print(api_list_all)

on_message_handlers = { 
						"!btc":			current_btc_price }

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