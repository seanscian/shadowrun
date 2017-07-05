#!/usr/bin/env ruby
require 'cgi'
require 'json'
require 'net/http'
require 'uri'
require 'sqlite3'

	# Conventions:
	# Comments are tabbed one extra level in.
	# Debugging is commented at head-of-line, regardless of indentation.

cgi = CGI.new

	# This is a cheap trick. CGI accumulates output and responds accordingly
	# so I can get timeouts even when I try to use this:
	#   cgi.out("status" => "OK", "type" => "text/plain", "connection" => "close") { "" }
	# The script has to terminate for anything with content length specified
	# so Apache can release the body with the correct Content-Length header.

	# However, if I print raw output I can specify chunked transfer encoding,
	# with an immediate end-of-chunked-transfer 0-byte chunk, Apache seems
	# to consume this and release a Content-Length: 0 response very quickly.

puts("Content-type: text/plain\r\nTransfer-Encoding: Chunked\r\n\r\n0\r\n\r\n")
database = 'rpdb'
	# Callbacks POST a JSON object as the HTML-encoded value of the "payload"
	# CGI variable. This turns it into a Ruby hash… beacuase we’re in Ruby.

	# Sanitize the input token, though the database *file* permissions are read-
	# only, so there shouldn’t be anything that can damage the database, but
	# I would like to avoid anything like shell scriping or other injections.
#STDERR.puts("Received: #{cgi["token"]}") #
token = cgi["token"].gsub(/[^0-9A-Za-z]/, '')
token = token[0,24]
#STDERR.puts("Current: #{token}") #

	# Use SQLite to see if the token we receive is in the database.
	#    Does anyone have a better idea than this? I don’t care about the
	#    actual token, since I only want to know if the query returned
	#    something.
	# Also, I’ll open the database once here. It there’s no token, it
	#    gets closed on exit, otherwise it gets used later, so no wasting
	#    time on multiple SQLite3::Database.new calls.
rpdb = SQLite3::Database.new(database)

if rpdb.execute("select token from tokens where token is \"#{token}\"").length == 0
	STDERR.puts('You’re not supposed to be here.')
	exit
else
#	STDERR.puts('PLAYER ONE HAS ENTERED THE GAME!') #
end

	# Sanitize channel_id, user_id
$channel_id = cgi["channel_id"].gsub(/[^0-9A-Za-z]/, '')
$channel_id = $channel_id[0,9]

user_id = cgi["user_id"].gsub(/[^0-9A-Za-z]/, '')
user_id = user_id[0,9]

text = cgi['text']
sl_user = cgi['user_name']

db_config = rpdb.execute("select config from channels where channel is \"#{$channel_id}\" limit 1")

case
when db_config.length == 0
	db_config = 0
else
	db_config = db_config[0][0]
		# Get the game/character information and GM authorization.
	game = rpdb.execute("select game from global where config is \"#{db_config}\" limit 1")[0][0]
	sl_user = rpdb.execute("select charname from characters where config is \"#{db_config}\" and slack_user is \"#{user_id}\" limit 1")[0][0]
	gm_auth = rpdb.execute("select GM from characters where config is \"#{db_config}\" and slack_user is \"#{cgi['user_id']}\" limit 1")[0][0]
	$chat_hook = rpdb.execute("select chat_hook from global where config is \"#{db_config}\" limit 1")[0][0]
	chat_icon = rpdb.execute("select picture from characters where config is #{db_config} and slack_user is \"#{cgi['user_id']}\" limit 1")[0][0]
	$default_icon = rpdb.execute("select default_icon from global where config is #{db_config}")[0][0]
	online_icon = rpdb.execute("select icon from online where config is #{db_config}")[0][0]
	online_name = rpdb.execute("select name from online where config is #{db_config}")[0][0]
	name_pattern = rpdb.execute("SELECT DISTINCT charname FROM characters WHERE config IS #{db_config} AND slack_user IS NOT \"#{user_id}\" and GM is null")
end

emote_name = /^(\w+)/.match(sl_user)[1]

if chat_icon.to_s == ''
	chat_icon = $default_icon
end

help_header = "*#{game} In-Character Chat #{$PROGRAM_NAME.gsub(/.*_|.cgi/, '')} in-line help*\n"

	# There’s going to be a lot of posting JSON to Slack.
def post_message(url,message)
	uri = URI.parse(url)
	http = Net::HTTP.new(uri.host, uri.port)
	http.use_ssl = true

	request = Net::HTTP::Post.new(
		uri.request_uri,
		'Content-Type' => 'application/json'
	)
	request.body = message.to_json
#	STDERR.puts(request.body) #

	response = http.request(request)
#	STDERR.puts(response.body) #
end

def mention(message)
	name_pattern = rpdb.execute("SELECT DISTINCT charname FROM characters WHERE config IS #{db_config} AND slack_user IS NOT \"#{user_id}\" and GM is null")
end

def chatter(username,icon_url,text,priv_footer)
	message = {
		"username" => username,
		"icon_url" => icon_url,
		"text" => text,
		"channel" => $channel_id,
		"attachments" => [ { "footer" => priv_footer } ]
	}
	post_message($chat_hook,message)
end

def emoter(emote_name,text,priv_footer)
	text = text.gsub('/me',emote_name.to_s)
	text = text.gsub('_','')
	text = text.gsub(emote_name.to_s,"*#{emote_name.to_s}*")
	message = {
		"username" => "­",
		"icon_url" => $default_icon,
		"text" => "_#{text}_",
		"channel" => $channel_id,
		"attachments" => [ { "footer" => priv_footer } ]
	}
	post_message($chat_hook,message)
end

command = cgi["command"]

if gm_auth.to_s.length > 0
	gm_help = "As an authorized GM, you have access to the `#{command} /gm` sub-command, allowing a GM to use an arbitrary name in a message. Type `#{command} /gm` for additional help."
else
	gm_help = ''
end

case text
when ""
	message = {
		"response_type" => "ephemeral",
		"text" => help_header,
		"attachments" =>
			[
				{
					"mrkdwn_in" => [ "text", "pretext" ],
					"pretext" => "Properly configured for your game, the default operation is to take a message you type (the text can contain Slack markdown) and display it as in-character talking, e.g. `#{command} I have a _*bad*_ feeling about this!` will display like this:",
					"author_name" => sl_user,
					"text" => "I have a _*bad*_ feeling about this!",
					"author_icon" => chat_icon
				},
				{
					"mrkdwn_in" => [ "text", "pretext" ],
					"pretext" => "If you type `#{command} /me smirks.`, it formats your message as an emote, for example:",
					"author_name" => "­",
					"author_icon" => $default_icon,
					"text" => "_*#{emote_name}* smirks._"
				},
				{
					"mrkdwn_in" => [ "text", "pretext" ],
					"pretext" => "*In Progress:* The format `#{command} %s We have trouble inbound!` formats your message as a form of group communication (online, telepathic, etc.), like this:",
					"author_icon" => online_icon.to_s,
					"author_name" => online_name.to_s,
					"text" => "formatted text"
				},
				{
					"mrkdwn_in" => [ "text", "pretext" ],
					"X-pretext" => "*In Progress:* In-character direct messages can be sent to any Slack user when sourced from a game channel by putting `/msg @username` after `#{command}`, for example, `#{command} /msg @username /me waves frantically.` Messages will be delivered in-character directly to the user and cloned to the sender. Replying to messages cannot be done via slackbot; it *must* be done from a configured gaming channel. This is awkward, but functional."
				},
				{
					"mrkdwn_in" => [ "text", "pretext" ],
					"pretext" => gm_help
				}
			]
	}

	post_message(cgi["response_url"],message)
	exit
when /^\/gm(.*)/
	gm_text = /\S.*? +.*? *$/.match($1)
	if gm_auth.to_s.length > 0
		case gm_text.to_s
		when ""
			message = {
				"response_type" => "ephemeral",
				"text" => "This allows the GM use an arbitrary name in a message.\n\n`/gm_Character_Name Message text goes here.`\n\nThe `gm_` will be stripped and all underscores in the remaining `Character_Name` will be converted to a whitespace, e.g. `#{command} /gm_Character_Name This is a message.` will display like this:",
				"attachments" =>
					[
						{
							"mrkdwn_in" => [ "text", "pretext" ],
							"author_name" => "Character Name",
							"text" => "This is a message.",
							"author_icon" => $default_icon
						},
						{
							"mrkdwn_in" => [ "text", "pretext" ],
							"pretext" => "To display character names with underscores in them, use a character other than an underscore after `/gm`, e.g. `/gm!The!big_SMALL Your message.` will display like this:",
							"author_name" => "The big_SMALL",
							"text" => "Your message.",
							"author_icon" => $default_icon
						},
#						{
#							"mrkdwn_in" => [ "pretext", "text" ],
#							"pretext" => "If you provide no character name, the text will post with “%s” as the sender, like this: `%s This is a message.`",
#							"author_name" => "%s",
#							"text" => "This is a message.",
#							"author_icon" => $default_icon
#						},
						{
							"mrkdwn_in" => [ "pretext", "text" ],
							"pretext" => "Like the non-GM version, `/gm` accepts the `/me` for an emote (and, soon, group communication), e.g. `/rp /gm_Mr._Johnson /me seethes with unbridled hatred.` will display like this:",
							"author_name" => "­",
							"text" => "_*Mr. Johnson* seethes with unbridled hatred._",
							"author_icon" => $default_icon
						}
					]
			}
			post_message(cgi["response_url"],message)
			exit
		when /^\S.*? +\/me .*? *$/
			emote_text = /^(\S)(.*?) +(\/me .*?) *$/.match(gm_text.to_s)
			sl_user = emote_text[2].gsub(emote_text[1],' ')
			emoter(sl_user,emote_text[3].to_s,nil)
			exit
		when /^\S.*? +(?:.*? *)$/
			chat_text = /^(\S)(.*?) +(?:(.*?) *)$/.match(gm_text.to_s)
			sl_user = chat_text[2].gsub(chat_text[1],' ')
			chatter(sl_user,$default_icon,chat_text[3].to_s,nil)
			exit
		end
		exit
	else
		message = {
			"response_type" => "ephemeral",
			"text" => "You are not a GM on this channel."
		}
		post_message(cgi["response_url"],message)
		exit
	end
when /^(\/me .*?) *$/
	emoter(emote_name,$1.to_s,nil)
	exit
when /^(?:(.*?) *)$/
	chatter(sl_user,chat_icon,$1.to_s,nil)
	exit
end
