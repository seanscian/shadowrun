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

	# This is a cheap trick. Apache CGI appears to accumulates output and
	# release periodically, so I can get timeouts even when I try to use this:
#cgi.out("status" => "OK", "type" => "text/plain", "connection" => "close") { "" }
	# The script has to terminate for anything with content length specified
	# so Apache can release the body with the correct Content-Length header.

	# However, if I specify chunked transfer encoding, with an immediate end-of-
	# chunked-transfer 0-byte chunk, Apache seems to consume this and release a
	# Content-Length: 0 response very quickly.

puts("Content-type: text/plain\r\nTransfer-Encoding: Chunked\r\n\r\n0\r\n\r\n")

	# Even so, Apache seems to queue the response occasionally; timeouts still
	# occur. I have to tear down that output channel so Apache releases the
	# response as soon as possible, so this ends up being the real solution.
STDOUT.close

database = 'rpdb'
	# Callbacks POST a JSON object as the HTML-encoded value of the "payload"
	# CGI variable. This turns it into a Ruby hash… beacuase we’re in Ruby.

	# Sanitize the input token, though the database *file* permissions are read-
	# only, so there shouldn’t be anything that can damage the database, but
	# I would like to avoid anything like shell scriping or other injections.
#STDERR.puts("Received: #{cgi["token"]}")
token = cgi["token"].gsub(/[^0-9A-Za-z]/, '')
token = token[0,24]
#STDERR.puts("Current: #{token}")

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
#else
#	STDERR.puts('PLAYER ONE HAS ENTERED THE GAME!')
end

	# Sanitize channel_id, user_id
channel_id = cgi["channel_id"].gsub(/[^0-9A-Za-z]/, '')
channel_id = channel_id[0,9]

user_id = cgi["user_id"].gsub(/[^0-9A-Za-z]/, '')
user_id = user_id[0,9]

text = cgi['text']

case cgi["command"]
when "/mroll"
	capture = /^([1-9]{1})(?![0-9])  *(.*?) *$/.match(text)
	iterations = capture[1].to_i or STDERR.puts "Bad /mroll"
	text = capture[2] or STDERR.puts "Bad /mroll"
else
	iterations = 1
end

sl_user = cgi['user_name']

db_config = rpdb.execute("select config from channels where channel is \"#{cgi["channel_id"]}\" limit 1")

case
when db_config.length == 0
	db_config = 0
else
	db_config = db_config[0][0]
		# Get the game/character information and GM authorization.
	game = rpdb.execute("select game from global where config is \"#{db_config}\" limit 1")[0][0].to_s
	begin
		sl_user = rpdb.execute("select charname from characters where config is \"#{db_config}\" and slack_user is \"#{cgi['user_id']}\" limit 1")[0][0].to_s
	rescue
		sl_user = cgi['user_name']
	end
	begin
		gm_auth = rpdb.execute("select GM from characters where config is \"#{db_config}\" and slack_user is \"#{cgi['user_id']}\" limit 1")[0][0].to_s
	rescue
		gm_auth = ''
	end
	begin
		chat_hook = rpdb.execute("select chat_hook from global where config is \"#{db_config}\" limit 1")[0][0].to_s
	end
	begin
		chat_icon = rpdb.execute("select picture from characters where config is #{db_config} and slack_user is \"#{cgi['user_id']}\" limit 1")[0][0].to_s
	rescue
		chat_icon = ''
	end
	begin
		default_icon = rpdb.execute("select default_icon from global where config is #{db_config}")[0][0].to_s
	rescue
		default_icon = ''
	end
end

chat_icon == '' && chat_icon = default_icon
	# D6 string, for fun (read: Shadowrun).
SIX_SIDES = "⚀⚁⚂⚃⚄⚅"

help_header = "*#{game} Roller #{$PROGRAM_NAME.gsub(/.*_|.cgi/, '')} in-line help*\n"

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
#	STDERR.puts(request.body)

	response = http.request(request)
#	STDERR.puts(response.body) #
end

#help_header = "*`#{cgi["command"]}` in-line help*"
help_text = <<HELPTEXT
This command accepts several dice roll types:

*1.* Roll a _Shadowrun_ dice pool of the format `p+e`, e.g. `#{cgi["command"]} 5+3`, where 5 is your dice pool and 3 is your Edge dice. You can omit either, but not both, e.g. `#{cgi["command"]} 5` or `#{cgi["command"]} +3`. This type also accepts optional [Limit] and (Threshold), e.g. `#{cgi["command"]} 10+2 (3)`, `#{cgi["command"]} 10+2 [5] (3)`, or `#{cgi["command"]} 10+2 [4]`.

The color of the sidebar will be green if you rolled any hits, yellow if you didn’t. Red indicates a *Glitch*, while black means *Critical Glitch*. If a Threshold was supplied, green indicates success, yellow indicates failure.

Magicians can, after their roll command, specify the dice to resist drain (and a comment) with the `/drain` token, e.g. `#{cgi["command"]} 18 [8] Clout /drain 13 S3`. This example would perform the roll of 18 pool dice, limit 8, with the comment “Clout”. It would be followed immediately by a roll of 13 dice with the comment “Resist drain for Clout S3”.

Technomancers can do the same thing, using the `/fading` token. (Technically, magicians can use the `/fading` token and technomancers can use the `/drain` token. It’s the same code.)

*2.* Roll a _Shadowrun_ initiative roll using the format `r+i`, e.g. `#{cgi["command"]} /init 9+4`, where 9 is your Reaction a 4 is your effective Initiative pool. If you omit the +#, e.g. `#{cgi["command"]} /init 9`, the roller assumes a single initiative die.

*3.* Roll a Star Wars Boost, Setback, Ability, Difficulty, Proficiency, Challenge, and Force roll using the format `#b#s#a#d#p#c#f`. Each element is optional, but the order is strict.  For example, you can roll `2b3a1p` for 2 Boost, 3 Ability, 1 Proficiency, but they *must* be in the order specified.

*4.* Roll the more standard gaming format of `NdX±Y`, e.g. `#{cgi["command"]} 4d6+2`, `3d8-2`, or `d100`. Omitting the number of dice to roll defaults to 1 rolled die. `d100` can be shortened to `d00`, `d0`, or `d%`. You can now add up to two additional die rolls; the formats are: `NdX±Y`, `NdX±Y±N'dX'±Y'`, `NdX±Y±N'dX'±Y±N"dX"±Y"`.

For example, for an event like damage (1d4) plus sneak attack bonus (1d6) plus strength bonus (3), you would roll `#{cgi["command"]} d4+d6+3`. As the parser is very simple you can unprison your think rhino and roll this obscenity: `/roll 3d7-2-4d3+8+22d2+2`

Any roll will accept, after the roll syntax, a comment to help identify the roll’s purpose, e.g. `#{cgi["command"]} 4+2 Bad Guy #1 Dodge`.

If you use the command `/mroll`, you can specify multiple rolls; typing a number between 1 and 5 after `/mroll`, e.g. `/mroll 3 /init 11+1 Flyspy`, will cause that number of rolls to be made. The number of the roll will be shown, appended to any comment if one was provided.

*IMPORTANT:* Tab no longer repeats the last command in Slack, so the old trick of using a zero dice in the unused fields isn’t as useful anymore. Consider copy/pasting something to the private chat Slack gives you with yourself, e.g. `#{cgi["command"]} 1b0s2a2d1p0c0f`, so you can revisit that for formatting. Of course, you can always just invoke this help and copy paste it from here.

Finally, you can roll dice generically in any Channel or Direct Message; no specific character name will be attached to the roll, but all other functions remain unchanged. This means you can even use `/roll` in your own direct message channel if you don’t want to share the results.
HELPTEXT

case text
when ""
#	STDERR.puts('Display Help.') #
	message = {
		"response_type" => "ephemeral",
		"text" => "#{help_header}\n#{help_text}"
	}

	post_message(cgi["response_url"],message)
when /^\/init +([1-9]{1}[0-9]?)(?:\+([1-5]{1}))?(?: +(.*?))? *$/
#	STDERR.puts("found init: #{text}") #
#	STDERR.puts("Reaction: ", $1) #
#	STDERR.puts("Initiative Dice: ", $2) #
#	STDERR.puts("Comment: ", $3) #

	case $2.to_i
	when 0
		initiative_dice = 1
#		STDERR.puts("No dice, setting to 1.") #
	else
		initiative_dice = $2.to_i
	end
#		STDERR.puts("Initiative Dice: #{initiative_dice}") #

		# Delimit comment, if present.
	case $3.to_s
	when ''
		comment = ''
	else
		comment = " — #{$3}"
	end

	for iteration in 1..iterations
			# Zero indexing the rolls, so your initiative is Reaction plus
			# the number of initiative dice (they’ll always roll at least 1)
			# then the randomizer adds 0–5 for each die, making Initiative
			# Your Reaction + 1–6 for each die. Math ops are reduced.

			# Also the die string is zero-indexed, so that’s one less math
			# operation for that string as well.
#		total = $1.to_i + $2.to_i
		total = $1.to_i + initiative_dice
		roll_string = ''
		for i in 1..initiative_dice
			dieroll = rand(6)
#			STDERR.puts("Rolled: ", SIX_SIDES[dieroll,1]) #
			roll_string = "#{roll_string}#{SIX_SIDES[dieroll,1]} "
			total += dieroll
		end

			# If /mroll was called format/number the comment
		if iterations > 1
			case comment
			when ''
				iter_comment = " — ##{iteration}"
			else
				iter_comment = " ##{iteration}"
			end
		end

		reinit_state = "#{user_id} #{total} 0"
		message = {
			"response_type" => "in_channel",
			"text" => "*#{sl_user}#{comment}#{iter_comment}*",
			"attachments" => [
				{
					"color" => "#764FA5",
					"mrkdwn_in" => [ "text" ],
					"callback_id" => "re_init",
					"thumb_url" => chat_icon,
					"fields" => [
						{
							"title" => "Initiative: #{total}",
							"short" => "true"
						},
						{
							"value" => "Reaction #{$1.to_i} + #{roll_string}\n",
							"short" => "true"
						}
					],
					"actions" => [
						{
							"style" => "primary",
							"name" => "up_stat",
							"text" => "+1",
							"type" => "button",
							"value" => reinit_state
						},
						{
							"style" => "danger",
							"name" => "dn_stat",
							"text" => "−1",
							"type" => "button",
							"value" => reinit_state
						},
						{
							"style" => "primary",
							"name" => "up_init",
							"text" => "+🎲",
							"type" => "button",
							"value" => reinit_state
						},
						{
							"style" => "danger",
							"name" => "dn_init",
							"text" => "−🎲",
							"type" => "button",
							"value" => reinit_state
						}
					]
				}
			]
		}

		post_message(cgi["response_url"],message)
	end
	# Shadowrun Dice Pool, Edge, Limit, Threshold, Comment
	#    Pool: 1-2 digits, optional, capture group 1
	#    Edge: +1 digit, optional, capture group 2
	#    Limit: [1-2] digits, optional, capture group 3
	#    Threshold: 1-2 digits, optional, capture group 4
	#    Remainder is a comment, capture group 5…
	#    Unless the /drain or /fading key is used, which is the drain/fading resist pool, capture group 6.
#when /^(?:(\d{1,2})?(?:\+(\d))?)(?: +\[(\d{1,2})\])?(?: +(\d{1,2}))?(?: +(.*?)(?i: *\/(drain|fading) +(\d{1,2})(?: +(.*?))?)?)? *$/
when /^(?:(\d{1,2})?(?:\+(\d))?)(?: +\[(\d{1,2})\])?(?: +\((\d{1,2})\))?(?: +(.*?)(?i: *\/(drain|fading) +(\d{1,2})(?: +(.*?))?)?)? *$/
	pool = $1.to_i
	edge = $2.to_i
	edge == 0 && limit = $3.to_i or limit = 100 # Rolled Edge? No Limit
	limit == 0 && limit = 100 # Set a limit of 0? No Limit
	threshold = $4.to_i
	drain_fade = $6.to_s
	drain_pool = $7.to_i
	cap_comment = $5.to_s
	drain_comment = $8.to_s

	case $5.to_s
	when ''
		comment = ''
	else
		comment = " — #{$5}"
	end

	def explosion
#		STDERR.puts("BOOM!") #
		case rand(6)
		when 5
#			STDERR.puts("XPLD HIT!") #
			$hits += 1
				# Probability should prevent an endless loop.
			explosion
		when 4
#			STDERR.puts("XPLD HIT!") #
			$hits += 1
		end
	end

	for iteration in 1..iterations

		if iterations > 1
			case comment
			when ''
				iter_comment = " — ##{iteration}"
			else
				iter_comment = " ##{iteration}"
			end
		end

#		STDERR.puts("Pool: #{pool} Edge: #{edge} Threshold: #{threshold} Comment: #{comment}#{iter_comment}") #
		color = 'good'
		$hits = 0
		ones = 0

			# Zero-indexing here to save on math operations, commented well
			# above in the initiative section.

			# Roll the dice in your pool
		for roll in 1..pool
				# Here’s the proper randomized roll
			case rand(6)
				# This is a zero-failure, with possibility of six (for edge)
#			case rand(2)+4
				# This rolls all 1s
#			case 0
				# At this point, you get the idea. Never case 5; it’s an endless loop if Edge is rolled
			when 5
#				STDERR.puts("POOL ROLL #{roll} HIT!") #
				$hits += 1
				edge > 0 && explosion
			when 4
#				STDERR.puts("POOL ROLL #{roll} HIT!") #
				$hits += 1
			when 0
#				STDERR.puts("POOL ROLL #{roll} ONE!") #
				ones += 1
#			else
#				STDERR.puts("POOL ROLL #{roll} MISS!") #
			end
		end

			# Roll edge dice.
		for roll in 1..edge
				# Here’s the proper randomized roll
			case rand(6)
				# This is a zero-failure, with possibility of six (for edge)
#			case rand(2)+4
				# This rolls all 1s
#			case 0
				# At this point, you get the idea. Never case 5; it’s an endless loop if Edge is rolled
			when 5
#				STDERR.puts("EDGE ROLL #{roll} HIT!") #
				$hits += 1
				explosion # Edge dice, so Rule of Six always applies
			when 4
#				STDERR.puts("EDGE ROLL #{roll} HIT!") #
				$hits += 1
			when 0
#				STDERR.puts("EDGE ROLL #{roll} ONE!") #
				ones += 1
#			else
#				STDERR.puts("EDGE ROLL #{roll} MISS!") #
			end
		end

			# Glitch Test (1s on more than ½ the dice rolled)
		if ones > ( pool + edge ) / 2
			glitch = ' Glitch!'
			color = 'danger'
			cc_action = 'Eliminate'
				# cgc is used by the reroll bot: 1 glitch, 2 critical
			cgc = 1
				# No hits is a critical glitch, black color
			if $hits == 0
				cgc = 2
				critical = ' Critical'
				color = '000000'
				reminder = ' You cannot spend two Edge to completley eliminate a Critical Glitch.'
				cc_action = 'Downgrade Critical'
			end

			edge == 0 && cc_button = {
				"name" => "close_call",
				"text" => "Close Call…",
				"type" => "button",
				"value" => color,
				"confirm" => {
					"title" => "#{cc_action} Glitch?",
					"text" => "This will cost you one Edge point.#{reminder}",
					"ok_text" => "Yes",
					"dismiss_text" => "No"
				}
			}
		end

			# Misses are needed for reroller dialogue box
		misses = pool + edge - $hits
		second_chance_average = misses / 3
		likely_total = $hits + second_chance_average
		misses != 1 && plural = 'es'
		case
		when ( misses * 3 / 2 ) > pool
			comparison = 'above '
			one_ninth = pool / 9
			case
			when misses > pool - one_ninth
				adverb = 'well '
			when misses <= pool - ( one_ninth * 2 )
				adverb = 'slightly '
			end
		when ( misses * 3 / 2 ) < pool
			comparison = 'below '
			one_ninth = pool / 9
			case
			when misses < one_ninth
				adverb = 'insanely '
			when misses >= one_ninth && misses <= one_ninth * 2
				adverb = 'well '
			when misses > one_ninth * 4
				adverb = 'slightly '
			end
		else
			comparison = ''
			adverb = ''
		end

			# If Edge was not rolled (no Push the Limits)…
			#    and if there were misses…
			#    and if the limit was not reached…
			#    Then provide a Second Chance!
		STDERR.puts "E:#{edge} M:#{misses} H:#{$hits} L:#{limit}"
		if edge == 0 and misses > 0 and $hits < limit
			second_chance = {
				"name" => "second_chance",
				"text" => "Second Chance…",
				"type" => "button",
				"value" => "#{user_id} #{$hits.to_i} #{misses.to_i} #{threshold.to_i} #{cgc.to_i} #{limit.to_i}",
				"confirm" => {
					"title" => "Reroll #{misses} Miss#{plural}?",
					"text" => "This will cost you one Edge point. #{misses} miss#{plural} is #{adverb}#{comparison}average. The number of likely additional hits by this Second Chance is #{second_chance_average} for a new hit total of #{likely_total}.", # if that helps you make up your mind.
					"ok_text" => "Yes",
					"dismiss_text" => "No"
				}
			}
		else
			second_chance = nil
		end

			# Test against Limit
		if limit > 0 && $hits > limit
			overflow = "Total Hits: #{$hits}"
			$hits = limit
		else
			overflow = nil
		end

		net = nil
		net_string = nil
		if threshold > 0
			if $hits >= threshold
				net = $hits - threshold
				result = "Success!"
				net == 1 && net_string = '1 Net Hit.' or net_string = "#{net} Net Hits."
			else
				result = 'Failure.'
				color == 'good' && color = 'warning'
			end
		else
			$hits == 1 && result = '1 Hit.' or result = "#{$hits} Hits."
			$hits == 0 && color == 'good' && color = 'warning'
		end

			# Threshold or Limit were specified, put them on the second info
			#    line, otherwise, just have an empty threshold_string.
			# TODO: rename the variable threshold_string to second_line or
			#    something like that.
		if threshold > 0 or limit > 0
			detail = Array.new
			limit > 0 && limit < 100 && detail[detail.length] = "Limit: #{limit}"
			threshold > 0 && detail[detail.length] = "Threshold: #{threshold}"
			threshold_string = "\n#{detail.join(' ')}"
		else
			threshold_string = nil
		end

			# If /mroll was called format/number the comment
		if iterations > 1
			case comment
			when ''
				iter_comment = " — ##{iteration}"
			else
				iter_comment = " ##{iteration}"
			end
		end

		message = {
			"response_type" => "in_channel",
			"text" => "*#{sl_user}#{comment}#{iter_comment}*",
			"attachments" => [
				{
					"thumb_url" => chat_icon,
					"color" => color,
					"fields" => [
						{
							"title" => "#{result}#{critical}#{glitch}",
							"value" => net_string,
							"short" => true
						},
						{
							"value" => "Pool: #{pool} Edge: #{edge}#{threshold_string}",
							"short" => true
						},
					],
					"footer" => overflow,
					"callback_id" => "edge_effect",
					"actions" => [
						second_chance,
						cc_button
					]
				}
			]
		}
		post_message(cgi["response_url"],message)

#		STDERR.puts("Hits: #{$hits} Ones: #{ones} Misses: #{misses} #{threshold_string}, #{net_string}") #

		if drain_pool > 0
				# Just talk to yourself and roll again.
			callback = File.basename($0)
			uri = URI.parse("http://127.0.0.1/#{callback}")
			http = Net::HTTP.new(uri.host, uri.port)
			request = Net::HTTP::Post.new(
				uri.request_uri,
				'Content-Type' => 'application/x-www-form-urlencoded',
					# TODO: Make this a variable from somewhere else
				'Host' => 'shadowrun.seanscian.net'
			)

			request.body = "token=#{token}&channel_id=#{channel_id}&user_id=#{user_id}&command=#{cgi["command"].gsub(/mroll/,'roll')}&text=#{drain_pool} Resist #{drain_fade} for #{cap_comment}#{iter_comment} #{drain_comment}&response_url=#{cgi["response_url"]}"
#			STDERR.puts(request.body) #

			response = http.request(request)
#			STDERR.puts(response.body) #
		end
	end
when /^(?:(\d)b)?(?:(\d)s)?(?:(\d)a)?(?:(\d)d)?(?:(\d)p)?(?:(\d)c)?(?:(\d)f)?(?: +(.*?))? *$/
		# The FFG SW Roll!
	boost = $1.to_i
	setbk = $2.to_i
	abilt = $3.to_i
	dfclt = $4.to_i
	prfnc = $5.to_i
	chlng = $6.to_i
	force = $7.to_i

		# Delimit comment, if present.
	case $8.to_s
	when ''
		comment = ''
	else
		comment = " — #{$8.to_s}"
	end

	cheating = /^((?:\db)?(?:\ds)?(?:\da)?(?:\dd)?(?:\dp)?(?:\dc)?(?:\df)?)(?: +[^\t ].*?)? *$/.match(text)

	dice = {
		"boost" => {
			"adv" => [ 0, 0, 2, 1, 1, 0 ],
			"suc" => [ 0, 0, 0, 0, 1, 1 ]
		},
		"setbk" => {
			"fal" => [ 0, 0, 1, 1, 0, 0 ],
			"thr" => [ 0, 0, 0, 0, 1, 1 ]
		},
		"abilt" => {
			"adv" => [0, 0, 0, 0, 1, 1, 1, 2],
			"suc" => [0, 1, 1, 2, 0, 0, 1, 0]
		},
		"dfclt" => {
			"fal" => [0, 1, 2, 0, 0, 0, 0, 1],
			"thr" => [0, 0, 0, 1, 1, 1, 2, 1]
		},
		"prfnc" => {
			"adv" => [0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 0],
			"suc" => [0, 1, 1, 2, 2, 0, 1, 1, 1, 0, 0, 0],
			"tri" => [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1]
		},
		"chlng" => {
			"fal" => [0, 1, 1, 2, 2, 0, 0, 1, 1, 0, 0, 0],
			"thr" => [0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 0],
			"des" => [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1]
		},
		"force" => {
			"drk" => [1, 1, 1, 1, 1, 1, 2, 0, 0, 0, 0, 0],
			"lht" => [0, 0, 0, 0, 0, 0, 0, 1, 1, 2, 2, 2]
		}
	}

	for iteration in 1..iterations
		adv=0; suc=0; fal=0; thr=0; tri=0; des=0; drk=0; lht=0; sf_roll=0; sw_value=0
#		sw_detail = "#{cheating}\n"
		sw_detail = [[],[],[],[],[],[],[]]

		# If /mroll was called format/number the comment
		if iterations > 1
			case comment
			when ''
				iter_comment = " — ##{iteration}"
			else
				iter_comment = " ##{iteration}"
			end
		end

		for i in 1..boost
			roll = rand(6)
			boost_adv = dice["boost"]["adv"][roll]
			boost_suc = dice["boost"]["suc"][roll]
			adv += boost_adv
			suc += boost_suc
			sf_roll = 1
			sw_detail[0][i] = {
				"text" => "#{boost_adv} Advantage, #{boost_suc} Success",
				"value" => "boost_#{i}"
			}
		end
		for i in 1..setbk
			roll = rand(6)
			setbk_fal = dice["setbk"]["fal"][roll]
			setbk_thr = dice["setbk"]["thr"][roll]
			fal += setbk_fal
			thr += setbk_thr
			sf_roll = 1
			sw_detail[1][i] = {
				"text" => "#{setbk_thr} Threat, #{setbk_fal} Failure",
				"value" => "setbk_#{i}"
			}
		end
		for i in 1..abilt
			roll = rand(8)
			abilt_adv = dice["abilt"]["adv"][roll]
			abilt_suc = dice["abilt"]["suc"][roll]
			adv += abilt_adv
			suc += abilt_suc
			sf_roll = 1
			sw_detail[2][i] = {
				"text" => "#{abilt_adv} Advantage, #{abilt_suc} Success",
				"value" => "abilt_#{i}"
			}
		end
		for i in 1..dfclt
			roll = rand(8)
			dfclt_fal = dice["dfclt"]["fal"][roll]
			dfclt_thr = dice["dfclt"]["thr"][roll]
			fal += dfclt_fal
			thr += dfclt_thr
			sf_roll = 1
			sw_detail[3][i] = {
				"text" => "#{dfclt_thr} Threat, #{dfclt_fal} Failure",
				"value" => "dfclt_#{i}"
			}
		end
		for i in 1..prfnc
			roll = rand(12)
			prfnc_adv = dice["prfnc"]["adv"][roll]
			prfnc_suc = dice["prfnc"]["suc"][roll]
			prfnc_tri = dice["prfnc"]["tri"][roll]
			adv += prfnc_adv
			suc += prfnc_suc
			tri += prfnc_tri
			sf_roll = 1
			sw_detail[4][i] = {
				"text" => "#{prfnc_adv} Advantage, #{prfnc_suc} Success, #{prfnc_tri} Triumph",
				"value" => "prfnc_#{i}"
			}
		end
		for i in 1..chlng
			roll = rand(12)
			chlng_fal = dice["chlng"]["fal"][roll]
			chlng_thr = dice["chlng"]["thr"][roll]
			chlng_des = dice["chlng"]["des"][roll]
			fal += chlng_fal
			thr += chlng_thr
			des += chlng_des
			sf_roll = 1
			sw_detail[5][i] = {
				"text" => "#{chlng_thr} Threat, #{chlng_fal} Failure, #{chlng_des} Despair",
				"value" => "chlng_#{i}"
			}
		end
		for i in 1..force
			roll = rand(12)
			force_drk = dice["force"]["drk"][roll]
			force_lht = dice["force"]["lht"][roll]
			drk += force_drk
			lht += force_lht
			sw_detail[6][i] = {
				"text" => "#{force_lht} Light, #{force_drk} Dark",
				"value" => "force_#{i}"
			}
		end
#		STDERR.puts "FFG SW Roll ##{iteration}! #{boost} #{setbk} #{abilt} #{dfclt} #{prfnc} #{chlng} #{force} #{comment}#{iteration}" #
#		STDERR.puts "ADV: #{adv}  THR: #{thr}  SUC: #{suc}  FAL: #{fal}  TRI: #{tri}  DES: #{des}  DRK: #{drk}  LHT: #{lht}" #

		success = suc + tri
		failure = fal + des

		color = '#764FA5'; s_or_f = ''; a_or_t = ''
		t_or_d = Array.new; l_or_d = Array.new
		case sf_roll
		when 1
			case
			when success > failure
				color = 'good'
				sw_value = success - failure
				sw_value == 1 && s_or_f = '1 Success' or s_or_f = "#{sw_value} Successes"
				des > 0 && color = 'warning'
			else
				color = 'warning'
				sw_value = failure - success
				sw_value == 1 && s_or_f = '1 Failure' or s_or_f = "#{sw_value} Failures"
				sw_value == 0 && s_or_f = 'Failure'
				des > 0 && color = 'danger'
			end
		end

		adv > thr && a_or_t = "#{adv - thr} Advantage"
		thr > adv && a_or_t = "#{thr - adv} Threat"

		tri > 0 && t_or_d[t_or_d.length] = "#{tri} Triumph"
		des > 0 && t_or_d[t_or_d.length] = "#{des} Despair"
		t_or_d.length > 0 && t_or_d = t_or_d.join(" ")

		lht > 0 && l_or_d[l_or_d.length] = "#{lht} Light"
		drk > 0 && l_or_d[l_or_d.length] = "#{drk} Dark"
		l_or_d.length > 0 && l_or_d = l_or_d.join(" ")

			# If the roll is Force-only, left-justify
		if sf_roll == 0
			s_or_f = l_or_d
			l_or_d = nil
		end

#		STDERR.puts "COL: #{color}  #{s_or_f}  #{a_or_t}  #{t_or_d}" #

			# More complete debug, but information that’s displayed anyway.
#		debug = "#{boost}b#{setbk}s#{abilt}a#{dfclt}d#{prfnc}p#{chlng}c#{force}f\n#{success} Success #{failure} Failure #{adv} Advantage #{thr} Threat\n#{tri} Triumph #{des} Despair #{drk} Dark #{lht} Light"
#		debug = "#{cheating[1]}\n#{success} Success #{failure} Failure #{adv} Advantage #{thr} Threat"
		debug = "#{success} Success #{failure} Failure #{adv} Advantage #{thr} Threat"

		sw_detail_button = {
			"name" => "sw_detail_button",
			"text" => "#{cheating[1]}",
#			"text" => "#{debug}",
			"type" => "select",
			"option_groups" => [
				{
					"text" => "Roll",
					"options" => [
						{
							"text" => "#{cheating[1]}",
							"value" => "roll_string"
						},
						{
							"text" => "#{debug}",
							"value" => "roll_detail"
						}
					]
				},
				{
					"text" => "Boost",
					"options" => sw_detail[0]
				},
				{
					"text" => "Setback",
					"options" => sw_detail[1]
				},
				{
					"text" => "Ability",
					"options" => sw_detail[2]
				},
				{
					"text" => "Difficulty",
					"options" => sw_detail[3]
				},
				{
					"text" => "Proficiency",
					"options" => sw_detail[4]
				},
				{
					"text" => "Challenge",
					"options" => sw_detail[5]
				},
				{
					"text" => "Force",
					"options" => sw_detail[6]
				}
			]
		}

		message = {
			"response_type" => "in_channel",
			"text" => "*#{sl_user}#{comment}#{iter_comment}*",
			"attachments" => [
				{
					"fallback" => "Star Wars dice roll",
					"color" => color,
					"fields" => [
						{
							"title" => s_or_f,
							"value" => a_or_t,
							"short" => "true"
						},
						{
							"title" => l_or_d,
							"value" => t_or_d,
							"short" => "true"
						}
					],
					"footer" => "#{debug}",
					"thumb_url" => chat_icon,
					"actions" => [
						sw_detail_button
					]
				}
			]
		}

		post_message(cgi["response_url"],message)
	end
#when /^(\d{1,2})?d(\d{1,2}|100|%)([+-]\d{1,2})?(?: +([^\t ].*?))? *$/
	# This should support XdY±Z±AdB±C±DdE±F
when /^(\d{1,2})?d(\d{1,2}|100|%)([+-]\d{1,2})?(?:([+-])(\d{1,2})?d(\d{1,2}|100|%)([+-]\d{1,2})?)?(?:([+-])(\d{1,2})?d(\d{1,2}|100|%)([+-]\d{1,2})?)?(?: +([^\t ].*?))? *$/
		# XdY±Z
	x = $1.to_i
	y = $2.to_i
	z = $3.to_i

		# ±XpdYp±Zp
	p_op = $4.to_s
	xp = $5.to_i
	yp = $6.to_i
	zp = $7.to_i

		# ±XppdYpp±Zpp
	pp_op = $8.to_s
	xpp = $9.to_i
	ypp = $10.to_i
	zpp = $11.to_i

		# Lacking a number of dice, default to 1; d0=d100 (lame hack here:
		# the string "%" is accepted and cast to integer via to_i, rendering
		# it 0, which is why this works.)
	x == 0 && x = 1
	y == 0 && y = 100

	xp == 0 && xp = 1
	yp == 0 && yp = 100

	xpp == 0 && xpp = 1
	ypp == 0 && ypp = 100

		# Delimit comment, if present.
	case $12.to_s
	when ''
		iterations > 1 && comment = " — #" or comment = ''
	else
		iterations > 1 && comment = " — #{$12} #" or comment = " — #{$12}"
	end

	for iteration in 1..iterations
		iterations > 1 && iter_comment = iteration
		total = z
		total_p = zp
		total_pp = zpp
		counter = Hash.new
		counter_p = Hash.new
		counter_pp = Hash.new

			# I could make the roller a function, and that’d be better, but
			# duplicating it here for now.
		for i in 1..x
			roll = rand(1..y)
#			roll = y # Max Test
#			roll = 1 # Min Test
			counter[roll] = counter[roll].to_i + 1
			total += roll
		end
#		STDERR.puts "#{x}d#{y}#{$3} = #{total}#{comment}#{iter_comment}" #
#		STDERR.puts counter
		sorted = Hash[counter.sort_by { |key, val| key}]

		entered_roll_string = "#{x}d#{y}#{$3.to_s}"

		if p_op != ""
			for i in 1..xp
				roll = rand(1..yp)
#				roll = yp # Max Test
#				roll = 1 # Min Test
				counter_p[roll] = counter_p[roll].to_i + 1
				total_p += roll
			end
#			STDERR.puts "#{xp}d#{yp}#{$7} = #{total_p}#{comment}#{iter_comment}" #
#			STDERR.puts counter_p
			sorted_p = Hash[counter_p.sort_by { |key, val| key}]

			case p_op
			when "+"
				total += total_p
				entered_roll_string = "#{entered_roll_string}+#{xp}d#{yp}#{$7.to_s}"
			when "-"
				total -= total_p
				entered_roll_string = "#{entered_roll_string}−#{xp}d#{yp}#{$7.to_s}"
			end
		end

		if pp_op != ""
			for i in 1..xpp
				roll = rand(1..ypp)
#				roll = ypp # Max Test
#				roll = 1 # Min Test
				counter_pp[roll] = counter_pp[roll].to_i + 1
				total_pp += roll
			end
#			STDERR.puts "#{xpp}d#{ypp}#{$7} = #{total_pp}#{comment}#{iter_comment}" #
#			STDERR.puts counter_pp
			sorted_pp = Hash[counter_pp.sort_by { |key, val| key}]

			case pp_op
			when "+"
				total += total_pp
				entered_roll_string = "#{entered_roll_string}+#{xpp}d#{ypp}#{$11.to_s}"
			when "-"
				total -= total_pp
				entered_roll_string = "#{entered_roll_string}−#{xpp}d#{ypp}#{$11.to_s}"
			end
		end

		message = {
			"response_type" => "in_channel",
			"text" => "*#{sl_user}#{comment}#{iter_comment}*",
			"attachments" => [
				{
					"thumb_url" => chat_icon,
					"color" => "#0000ff",
					"fields" => [
						{
							"title" => total,
							"short" => true
						},
						{
#							"value" => "Roll: #{x}d#{y}#{$3.to_s.gsub(/-/,'−')}",
							"value" => "Roll: #{entered_roll_string.to_s.gsub(/-/,'−')}",
							"short" => true
						}
					],
					"footer" => "#{sorted.to_s}#{sorted_p.to_s}#{sorted_pp.to_s}"
				}
			]
		}

		post_message(cgi["response_url"],message)
	end
else
	message = {
		"response_type" => "ephemeral",
		"text" => "#{help_header}\nNí thuigim. 分からない。 I do not understand.\n\n#{help_text}\n\nI’m afraid what you typed—`#{cgi["command"]} #{text}`—made no sense. You can try to explain it to me, but it won’t work. It’s most likely you either mistyped something or you were trying to fool me, and I’m too simple to speculate on the former or fall for the latter."
	}

	post_message(cgi["response_url"],message)
end
