#!/usr/bin/env ruby
require 'cgi'
require 'json'
require 'net/http'
require 'uri'
require 'sqlite3'
require 'base64'

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
token = cgi["token"].gsub(/[^0-9A-Za-z]/, '')
token = token[0,24]

	# Use SQLite to see if the token we receive is in the database.
	#    Does anyone have a better idea than this? I don’t care about the
	#    actual token, since I only want to know if the query returned
	#    something.
	# Also, I’ll open the database once here. It there’s no token, it
	#    gets closed on exit, otherwise it gets used later, so no wasting
	#    time on multiple SQLite3::Database.new calls.
$rpdb = SQLite3::Database.new(database)

if $rpdb.execute("select token from tokens where token is \"#{token}\"").length == 0
	STDERR.puts('You’re not supposed to be here.')
	exit
end

	# Sanitize channel_id, user_id
$channel_id = cgi["channel_id"].gsub(/[^0-9A-Za-z]/, '')
$channel_id = $channel_id[0,9]

$user_id = cgi["user_id"].gsub(/[^0-9A-Za-z]/, '')
$user_id = $user_id[0,9]

text = cgi['text']
sl_user = cgi['user_name']

$db_config = $rpdb.execute("select config from channels where channel is \"#{$channel_id}\" limit 1")

case
when $db_config.length == 0
	$db_config = 0
else
	$db_config = $db_config[0][0]
		# Get the game/character information and GM authorization.
	game = $rpdb.execute("select game from global where config is \"#{$db_config}\" limit 1")[0][0]
	begin
		sl_user = $rpdb.execute("select charname from characters where config is \"#{$db_config}\" and slack_user is \"#{$user_id}\" limit 1")[0][0]
	rescue
		sl_user = cgi['user_name']
#		cgi['channel_name'] != "directmessage" && cgi['channel_name'] != "privategroup" &&
		STDERR.puts("Unconfigured ID #{cgi['user_id']} (#{cgi['user_name']}) in #{cgi['channel_id']} (#{cgi['channel_name']}).")
	end
	begin
		gm_auth = $rpdb.execute("select GM from characters where config is \"#{$db_config}\" and slack_user is \"#{cgi['user_id']}\" limit 1")[0][0]
	rescue
		gm_auth = nil
	end
	begin
		$chat_hook = $rpdb.execute("select chat_hook from global where config is \"#{$db_config}\" limit 1")[0][0]
	end
	begin
		chat_icon = $rpdb.execute("select picture from characters where config is #{$db_config} and slack_user is \"#{cgi['user_id']}\" limit 1")[0][0]
	rescue
		chat_icon = nil
	end
	begin
		$default_icon = $rpdb.execute("select default_icon from global where config is #{$db_config}")[0][0]
	rescue
		default_icon = nil
	end
	begin
		$online_prog = $rpdb.execute("SELECT program FROM online WHERE config IS #{$db_config} LIMIT 1")[0][0]
	rescue
		$online_prog = nil
	end
	begin
		$prefix = $rpdb.execute("SELECT prefix FROM online WHERE config IS #{$db_config} LIMIT 1")[0][0]
		$suffix = $rpdb.execute("SELECT suffix FROM online WHERE config IS #{$db_config} LIMIT 1")[0][0]
	rescue
		$prefix = '['
		$suffix = ']'
	end
	begin
		online_icon = $rpdb.execute("select icon from online where config is #{$db_config}")[0][0]
	rescue
		online_icon = nil
	end
	begin
		$online_command = $rpdb.execute("SELECT command FROM online WHERE config IS #{$db_config} LIMIT 1")[0][0]
	rescue
		$online_command = '/com'
	end
	begin
		online_name = $rpdb.execute("select name from online where config is #{$db_config}")[0][0]
	rescue
		online_name = nil
	end
	begin
		name_pattern = $rpdb.execute("SELECT DISTINCT charname FROM characters WHERE config IS #{$db_config} AND slack_user IS NOT \"#{$user_id}\" and GM is null")
	end
	begin
		alternates = $rpdb.execute("SELECT dest FROM chat_targets WHERE config IS #{$db_config} AND source IS \"#{$channel_id}\"")
	rescue
		alternates = nil
	end
end

if alternates.length > 0
		# The way the SQL query returns the array, I can only think of this
		# method to redefine the single-level $chat_targets array.
	$chat_targets = Array.new
	alternates.each { |chan| $chat_targets[$chat_targets.length] = chan[0] }
else
		# Create recipient array, for private messages.
	$chat_targets = [ $channel_id ]
end

	# Emote names are just the “first” name.
$emote_name = /^(\w+)/.match(sl_user)[1]

	# The pattern to look for “online” or “group” chat…
$online_pattern = Regexp.new("^(?:#{$online_command.to_s} +(.*?) *)$")

	# If the chat_icon defaulted or the character doesn’t have one, use the default game icon.
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

	# Receives a string of text to search for character names. highlight is true/false.
def mention(message,highlight)
	$rpdb.execute("SELECT DISTINCT substr(trim(charname),1,instr(trim(charname)||' ',' ')-1) FROM characters WHERE config IS #{$db_config} AND slack_user IS NOT \"#{$user_id}\" and GM is null").each {
		|x|
		if /\b#{x[0]}\b/.match(message.to_s)
			$rpdb.execute("SELECT DISTINCT slack_user FROM characters WHERE charname LIKE \"#{x[0]}%\" AND config IS #{$db_config}").each {
				|n|
				notify_message = {
					"text" => "#{x[0]} was mentioned by #{$emote_name} in ##{$channel_id}.",
					"channel" => n[0]
				}
				post_message($chat_hook,notify_message)
			}
			if highlight == true
				message.gsub!(x[0],"*#{x[0]}*")
			end
		end
	}
	return message
end

def matrix_formatter(user,text)
	if $online_prog.to_s == ""
		return "\`#{$prefix}#{text.gsub('`','')}#{$suffix}#{$emote_name}\ \<#{Time.new.to_i}\>`"
	else
		output = `online_progs/#{$online_prog} #{$user_id} #{Base64.strict_encode64(user)} #{Base64.strict_encode64(text)}`
		output.force_encoding(Encoding::UTF_8)
		return output
	end
end

def matrixer(username,sl_user,text,priv_footer)
	mention(text,false)
	matrix_text = matrix_formatter(sl_user,text)
	$chat_targets.each {
		|target|
		message = {
			"username" => username,
			"icon_url" => $default_icon,
			"text" => matrix_text,
			"channel" => target,
			"attachments" => [ { "footer" => priv_footer } ]
		}
		post_message($chat_hook,message)
	}
end

def chatter(username,icon_url,text,priv_footer)
	mention(text,false)
	$chat_targets.each {
		|target|
		message = {
			"username" => username,
			"icon_url" => icon_url,
			"text" => text,
			"channel" => target,
			"attachments" => [ { "footer" => priv_footer } ]
		}
		post_message($chat_hook,message)
	}
end

def emoter(emote_name,text,priv_footer)
	text.gsub!('/me',emote_name.to_s)
	text.gsub!('_','')
	text.gsub!(emote_name.to_s,"*#{emote_name.to_s}*")
	text = mention(text,true)
	$chat_targets.each {
		|target|
		message = {
			"username" => "­",
			"icon_url" => $default_icon,
			"text" => "_#{text}_",
			"channel" => target,
			"attachments" => [ { "footer" => priv_footer } ]
		}
		post_message($chat_hook,message)
	}
end

command = cgi["command"]

	# I use gm_help as a static entry in the ruby hash later; fewer conditionals this way.
gm_help = ''

	# Parse GM token and remove it from the text.
if /(?:\/gm\S\w+\b)/.match(text)
		# If the user is a GM, give substantive help and change actor name…
	if gm_auth.to_s.length > 0
		gm_help = "\n\nAs an authorized GM, you have access to the `#{command} /gm` sub-command, allowing a GM to use an arbitrary name in a message. Type `#{command} /gm` for additional help."
			# find /gm token and parse new name
		capture = /(?:\/gm(\S)(\w+)\b)/.match(text)
		sl_user = capture[2].gsub(capture[1],' ')
		$emote_name = sl_user
	else
			# …otherwise tell the person they’re not a GM…
		message = {
			"response_type" => "ephemeral",
			"text" => "You are not a GM on this channel."
		}
		post_message(cgi["response_url"],message)
		exit
	end
		# …and in either case, move the text along without the /gm token.
	text.gsub!(/(?:\/gm\S\w+\b) */,'')
end

	# remove /msg @username and capture the user for private message.
if /(?:\/msg +@\w+\b)/.match(text)
	capture = /(?:\/msg +(@\w+)\b)/.match(text)
	$chat_targets = [ $user_id, capture[1] ]
	priv_footer = "from <##{$channel_id}|#{cgi['channel_name']}> player <@#{$user_id}|#{cgi['user_name']}> to #{capture[1]}"
		# I feel safe doing this, because text has to move on without the /msg tokens.
	text.gsub!(/(?:\/msg +(@\w+)\b) */,'')
else
		# priv_footer is called by chatter and emote, so let’s make sure it always exists.
	priv_footer = nil
end

case text
when ""
	message = {
		"response_type" => "ephemeral",
		"text" => help_header,
		"attachments" => [
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
				"text" => "_*#{$emote_name}* smirks._"
			},
			{
				"mrkdwn_in" => [ "text", "pretext" ],
				"pretext" => "The format `#{command} #{$online_command} We have trouble inbound!` formats your message as a form of group communication (online, telepathic, etc.), like this:",
				"author_icon" => online_icon.to_s,
				"author_name" => online_name.to_s,
				"text" => matrix_formatter(sl_user,"We have trouble inbound!")
			},
			{
				"mrkdwn_in" => [ "text", "pretext" ],
				"pretext" => "In-character direct messages can be sent to any Slack user when sourced from a game channel by putting `/msg @username` after `#{command}`, for example, `#{command} /msg @username /me waves frantically.` Messages will be delivered in-character directly to the user and cloned to the sender. Replying to messages cannot be done via slackbot; it *must* be done from a configured gaming channel. This is awkward, but functional.#{gm_help}"
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
				"attachments" => [
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
	emoter($emote_name,$1.to_s,priv_footer)
	exit
when $online_pattern
	matrixer(online_name,sl_user,$1.to_s,priv_footer)
	exit
when /^(?:(.*?) *)$/
	chatter(sl_user,chat_icon,$1.to_s,priv_footer)
	exit
end
