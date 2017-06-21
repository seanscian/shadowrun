#!/usr/bin/env ruby
require 'json'
require 'net/http'
require 'uri'
require 'sqlite3'

	# Conventions:
	# Comments are tabbed one extra level in.
	# Debugging is commented at head-of-line, regardless of indentation.
	# Debugging should also be commented at end-of-line, so debugging
	#    statements to disable can be found more quickly.

	# This is more of a “just be safe and read the data without any
	#    interpretation.”
ARGF.binmode
slack_event = JSON.parse(ARGF.read)

	# Use SQLite to see if the token we receive is in the database.
	# Anyone have a better idea?
if SQLite3::Database.new('rpdb').execute("select distinct token from tokens where token is \"#{slack_event["token"]}\"").length == 0
	STDERR.puts('You’re not supposed to be here.')
	exit
else
#	STDERR.puts('PLAYER ONE HAS ENTERED THE GAME!') #
end

	# Token has been verified, so challenge response if verifying the
	#    URL, otherwise just respond to what’s probably an API call.
if slack_event["type"] == "url_verification"
	puts("Content-type: text/plain\r\n\r\n#{slack_event["challenge"]}")
	exit
else
		# This is a cheap trick. CGI accumulates output then sends the response
		#    through Apache, so I can get timeouts.

		# The script has to terminate for anything even with the content length
		#    specified so Apache can release the body with the correct
		#    Content-Length header.

		# However, if I print raw output I can specify chunked transfer encoding,
		#    with an immediate end-of-chunked-transfer 0-byte chunk, Apache seems
		#    consumes this and release a Content-Length: 0 response very quickly.
	puts("Content-type: text/plain\r\nTransfer-Encoding: Chunked\r\n\r\n0\r\n\r\n")
end

#slack_event["event"].each { |key,value| STDERR.puts "#{key} => #{value}" } #

	# Get the channel name, if it exists.
	# TODO: Sanitize the input.
channel_query = SQLite3::Database.new('rpdb').execute("select name from channels where name like \"%-rp\" and channel is \"#{slack_event["event"]["channel"]}\"")
if channel_query.length == 0
#	STDERR.puts("Anyone can talk here in #{slack_event["event"]["channel"]}") #
		# Just exit if anyone can talk here; there’s nothing left to do.
	exit
else
	channel_name = channel_query[0][0]
		# If a user actually put a message in here, take action: delete, repost, etc.
#	STDERR.puts("#{slack_event["event"]["channel"]} is a roleplay channel.") #
	if slack_event["event"].has_key?("user")
#		STDERR.puts "Acting on the message left at #{slack_event["event"]["ts"]}." #
#		slack_event["event"].each { |key,value| STDERR.puts "#{key} => #{value}" } #
			# TODO: Move this to a subroutine.
		uri = URI.parse("http://127.0.0.1/rp_1.2.2.cgi")
		http = Net::HTTP.new(uri.host, uri.port)
		request = Net::HTTP::Post.new(
			uri.request_uri,
			'Content-Type' => 'application/x-www-form-urlencoded',
			'Host' => 'shadowrun.seanscian.net'
		)

			# This is a legacy method. It’s terrible, but chat.delete isn’t otherwise available.
		api_token = SQLite3::Database.new('rpdb').execute("select distinct token from apitokens where team is \"#{slack_event["team_id"]}\" limit 1")
		if api_token.length != 0
			del_uri = URI.parse("https://slack.com/api/chat.delete")
			del_http = Net::HTTP.new(del_uri.host, del_uri.port)
			del_http.use_ssl = true
			del_request = Net::HTTP::Post.new(
				del_uri.request_uri,
				'Content-Type' => 'application/x-www-form-urlencoded',
			)
			del_request.body = "token=#{api_token[0][0]}&ts=#{slack_event["event"]["ts"]}&channel=#{slack_event["event"]["channel"]}"
#			STDERR.puts(del_request.body) #
			del_response = del_http.request(del_request)
#			STDERR.puts(del_response.body) #
		end

		case
		when slack_event["event"]["type"] == "message"
				# If the message is a slack emote, make it a bot emote.
			slack_event["event"]["subtype"] == "me_message" && emote = '/me ' or emote = ''

				# Build the POST and send it.
			request.body = "text=#{emote}#{slack_event["event"]["text"]}&token=#{slack_event["token"]}&user_id=#{slack_event["event"]["user"]}&channel_id=#{slack_event["event"]["channel"]}&channel_name=#{channel_name}"
#			STDERR.puts(request.body) #
			response = http.request(request)
#			STDERR.puts(response.body) #
		end
	end
end

exit
