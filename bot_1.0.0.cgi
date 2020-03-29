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

	# Callbacks POST a JSON object as the HTML-encoded value of the "payload"
	# CGI variable. This turns it into a Ruby hash… beacuase we’re in Ruby.
slack_post = JSON.parse(cgi['payload'])

	# Sanitize the input token.
#STDERR.puts("Received: #{slack_post["token"]}")
slack_post["token"].gsub!(/[^0-9A-Za-z]/, '')
slack_post["token"] = slack_post["token"][0,24]
#STDERR.puts("Current: #{slack_post["token"]}")

	# Use SQLite to see if the token we receive is in the database.
	# Anyone have a better idea?
if SQLite3::Database.new('rpdb').execute("select token from tokens where token is \"#{slack_post["token"]}\"").length == 0
	STDERR.puts('You’re not supposed to be here.')
	exit
else
#	STDERR.puts('PLAYER ONE HAS ENTERED THE GAME!')
end

	# D6 string, for fun (read: Shadowrun).
#die_string = "⚀⚁⚂⚃⚄⚅"
die_string = "①②③④⑤⑥"

	# Method to consume a Slack callback. As above, this is still a Ruby hash,
	# and stays that way until conversion into the request’s post body.
def update_original(slack_post)
	uri = URI.parse(slack_post["response_url"])
#	STDERR.puts(slack_post["response_url"])
	http = Net::HTTP.new(uri.host, uri.port)
	http.use_ssl = true

	request = Net::HTTP::Post.new(
		uri.request_uri,
		'Content-Type' => 'application/json'
	)
	request.body = slack_post["original_message"].to_json
#	STDERR.puts(request.body)

	response = http.request(request)
#	STDERR.puts(response.body)
end


	# Decide what to do based on callback_id
case slack_post["callback_id"]
when "re_init"
		# Get the roll state
	reroll = slack_post["actions"][0]["value"].split(" ")

	if slack_post["user"]["id"] != reroll[0]
#		STDERR.puts('That’s. Not. Yours.')
		exit
	end

	case slack_post["actions"][0]["name"]
	when "up_stat"
#		STDERR.puts("+1")
		reroll[2] = reroll[2].to_i + 1
		new_init = reroll[1].to_i + 1
	when "dn_stat"
#		STDERR.puts("-1")
		reroll[2] = reroll[2].to_i - 1
		new_init = reroll[1].to_i - 1
	when "up_init"
			# dieroll is 0-indexed, and since I’m using it for substrings
			# and can do the required math later, I don’t bother with the
			# convention of rand(#) + 1 to generate a 1-# range.
		dieroll = rand(6)
#		STDERR.puts("+#{dieroll+1}")
		new_init = reroll[1].to_i + dieroll + 1
		method = "+"
		slack_post["original_message"]["attachments"][0]["fields"][1]['value'] = "#{slack_post["original_message"]["attachments"][0]["fields"][1]['value']}#{method}#{die_string[dieroll,1]} "
	when "dn_init"
			# 0-indexed dieroll reason above; hasn’t changed here.
		dieroll = rand(6)
#		STDERR.puts("-#{dieroll+1}")
		new_init = reroll[1].to_i - dieroll - 1
			# This is a UTF-8 minus, not the thing you get when you press - on your keyboard.
		method = "−"
		slack_post["original_message"]["attachments"][0]["fields"][1]['value'] = "#{slack_post["original_message"]["attachments"][0]["fields"][1]['value']}#{method}#{die_string[dieroll,1]} "
	end

		# If the stat iself goes up and down, the displayed adjustment is
		# formatted here. Again, UTF-8 minus is used for display.
	case slack_post["actions"][0]["name"]
	when "up_stat","dn_stat"
		case
		when reroll[2].to_i < 0
			slack_post["original_message"]["attachments"][0]["fields"][0]['value'] = "−#{reroll[2].abs}"
		when reroll[2].to_i > 0
			slack_post["original_message"]["attachments"][0]["fields"][0]['value'] = "+#{reroll[2]}"
		else
			slack_post["original_message"]["attachments"][0]["fields"][0]['value'] = ''
		end
	end

		# Push the new state back into the Slack message
	st = "#{reroll[0]} #{new_init} #{reroll[2]}"
		# TODO: Enumerate the number of state tokens in actions?
		# Done, but can it be done better?
	slack_post["original_message"]["attachments"][0]["actions"].each_index do |x|
		slack_post["original_message"]["attachments"][0]["actions"][x]["value"] = st
	end

		# Instead of testing whether or not the new initiative has changed,
		# just put it in the hash. It has to have been set by a previous
		# operation, and the entire hash is pushed back to the messages as
		# a JSON object, so…
	slack_post["original_message"]["attachments"][0]["fields"][0]['title'] = "Initiative: #{new_init}"

	update_original(slack_post)
when "edge_effect"
	case slack_post["actions"][0]["name"]
	when "second_chance"
			# "#{user_id} #{$hits} #{misses} #{threshold} #{cgc}",
#		STDERR.puts(slack_post) #
		reroll = slack_post["actions"][0]["value"].split(" ")

		if slack_post["user"]["id"] != reroll[0]
#			STDERR.puts('That’s. Not. Yours.') #
			exit
		end

			# If Edge is being used, remove the callback buttons and other IDs
		slack_post["original_message"]["attachments"][0].delete("actions")
		slack_post["original_message"]["attachments"][0].delete("callback_id")
		slack_post["original_message"]["attachments"][0].delete("fallback")
		slack_post["original_message"]["attachments"][0].delete("id")
		slack_post["original_message"].delete("subtype")

		hits = reroll[1].to_i
		misses = reroll[2].to_i
		threshold = reroll[3].to_i
			# cgc: 1 = Glitch, 2 = Critical Glitch
		cgc = reroll[4].to_i
		limit = reroll[5].to_i
#		STDERR.puts("Limit: #{limit}") #
		pool = hits + misses
		slack_post["original_message"]["attachments"][0]["color"] = 'good'

#		STDERR.puts("initial hits: #{hits} dice to roll: #{misses}")

		ones = 0
		for iter in 1..misses
				# 0-index here? Comparison readability and debugging is just
				# off by one.
			case rand(6)
			when 4,5
				hits +=1
			when 0
				ones +=1
			end
		end

			# (Critical) Glitch test and formatting
		if ones > pool/2
			glitch = ' Glitch!'
			slack_post["original_message"]["attachments"][0]["color"] = 'danger'
			if hits == 0
				critical = ' Critical'
				slack_post["original_message"]["attachments"][0]["color"] = '#000000'
			end
		end

			# Test against Limit
		limit > 0 && hits > limit && hits = limit

			# Threshold test and formatting
		if threshold > 0
			if hits >= threshold
				net = hits-threshold
				result = 'Success!'
				net != 1 && netstring = "#{net} Net Hits." or netstring = "1 Net Hit."
			else
				result = 'Failure.'
				slack_post["original_message"]["attachments"][0]["color"] == 'good' && slack_post["original_message"]["attachments"][0]["color"] = 'warning'
			end
		else
			hits != 1 && result = "#{hits} Hits." or result = "1 Hit."
			hits == 0 && slack_post["original_message"]["attachments"][0]["color"] == 'good' && slack_post["original_message"]["attachments"][0]["color"] = 'warning'
#			hits == 0 && slack_post["original_message"]["attachments"][0]["color"] = 'warning'
		end

		case cgc
		when 1
#			STDERR.puts("You had a glitch before.") #
			glitch = ' Glitch!'
			slack_post["original_message"]["attachments"][0]["color"] = 'danger'
		when 2
#			STDERR.puts("You had a critical glitch before.") #
			critical = ' Critical'
			glitch = ' Glitch!'
			slack_post["original_message"]["attachments"][0]["color"] = '#000000'
		end

#		STDERR.puts("new hits: #{hits} new ones: #{ones}") #
			# Update original message
		slack_post["original_message"]["attachments"][0]["fields"][0]['title'] = "#{result}#{critical}#{glitch}"
		slack_post["original_message"]["attachments"][0]["fields"][0]['value'] = "#{netstring}"

		update_original(slack_post)
	when "close_call"
		case "#{slack_post["actions"][0]["value"]}"
		when "000000"
				# If it came in Critical Glitch, change color and remove "Critical"
			slack_post["original_message"]["attachments"][0]["fields"][0]['title'].slice! "Critical "
			slack_post["original_message"]["attachments"][0]["color"] = "danger"
		when "danger"
				# If it came in Glitch, change color and remove "Glitch!"
			slack_post["original_message"]["attachments"][0]["fields"][0]['title'].slice! " Glitch!"
			slack_post["original_message"]["attachments"][0]["color"] = "warning"
		end
			# Edge is being used, so remove the callback buttons and other IDs
		slack_post["original_message"]["attachments"][0].delete("actions")
		update_original(slack_post)
	end
end
