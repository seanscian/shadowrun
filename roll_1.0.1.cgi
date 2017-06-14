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
#STDERR.puts("Received: #{cgi["token"]}")
token = cgi["token"].gsub(/[^0-9A-Za-z]/, '')
token = token[0,24]
#STDERR.puts("Current: #{token}")

	# Use SQLite to see if the token we receive is in the database.
	# Anyone have a better idea?
if SQLite3::Database.new(database).execute("select token from tokens where token is \"#{token}\"").length == 0
	STDERR.puts('You’re not supposed to be here.')
	exit
else
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
rpdb = SQLite3::Database.new(database)

db_config = rpdb.execute("select config from channels where channel is \"#{cgi["channel_id"]}\" limit 1")

case
when db_config.length == 0
	db_config = 0
else
	db_config = db_config[0][0]
		# Get the game/character information and GM authorization.
	game = rpdb.execute("select game from global where config is \"#{db_config}\" limit 1")[0][0]
	sl_user = rpdb.execute("select charname from characters where config is \"#{db_config}\" and slack_user is \"#{cgi['user_id']}\" limit 1")[0][0]
	gm_auth = rpdb.execute("select GM from characters where config is \"#{db_config}\" and slack_user is \"#{cgi['user_id']}\" limit 1")[0][0]
	chat_hook = rpdb.execute("select chat_hook from global where config is \"#{db_config}\" limit 1")[0][0]
	chat_icon = rpdb.execute("select picture from characters where config is #{db_config} and slack_user is \"#{cgi['user_id']}\" limit 1")[0][0]
	default_icon = rpdb.execute("select default_icon from global where config is #{db_config}")[0][0]
end

	# D6 string, for fun (read: Shadowrun).
die_string = "⚀⚁⚂⚃⚄⚅"

#case sl_user
#when ""
#	channel_name != 'directmessage' && STDERR.puts("Unconfigured ID #{cgi['user_id']} (#{cgi['user_name']}) in #{cgi['channel_id']} (#{cgi['channel_name']})")
#end

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
help_text = "This command accepts several dice roll types:\n\n*1.* Roll a _Shadowrun_ dice pool of the format `p+e`, e.g. `#{cgi["command"]} 5+3`, where 5 is your dice pool and 3 is your Edge dice. You can omit either, but not both, e.g. `#{cgi["command"]} 5` or `#{cgi["command"]} +3`. This type also accepts optional Limit and Threshold, e.g. `#{cgi["command"]} 10+2 3`, `#{cgi["command"]} 10+2 [5] 3`, or `#{cgi["command"]} 10+2 [4]`.\n\nThe color of the sidebar will be green if you rolled any hits, yellow if you didn’t. Red indicates a *Glitch*, while black means *Critical Glitch*. If a Threshold was supplied, green indicates success, yellow indicates failure.\n\n*2.* Roll a _Shadowrun_ initiative roll using the format `r+i`, e.g. `#{cgi["command"]} /init 9+4`, where 9 is your Reaction a 4 is your effective Initiative pool.\n\n*3.* Roll a Star Wars Boost, Setback, Ability, Difficulty, Proficiency, Challenge, and Force roll using the format `#b#s#a#d#p#c#f`. Each element is optional, but the order is strict.  For example, you can roll `2b3a1p` for 2 Boost, 3 Ability, 1 Proficiency, but they *must* be in the order specified.\n\n*4.* Roll the more standard gaming format of `NdX±Y`, e.g. `#{cgi["command"]} 4d6+2`, `3d8-2`, or `d100`. Omitting the number of dice to roll defaults to 1 rolled die. `d100` can be shortened to `d00`, `d0`, or `d%`.\n\nAny of those will accept, after the roll syntax, a comment to help identify the roll’s purpose, e.g. `#{cgi["command"]} 4+2 Bad Guy #1 Dodge`.\n\nIf you use the command `/mroll`, you can specify multiple rolls; typing a number between 1 and 9 after `/mroll`, e.g. `/mroll 3 /init 11+1 Flyspy`, will cause that number of rolls to be made. The number of the roll will be shown, appended to any comment if one was provided.\n\n*HINT:* Tab repeats the last command, and many rolls will accept 0 as a number of dice to roll. For more complex rolls, specify zero dice in the unused fields and a tab-edit makes the roller easier to use. For example: `#{cgi["command"]} 1b0s2a2d1p0c0f`\n\nFinally, you can roll dice privately in your own direct message channel. The results are visible only to you and lets bots interact with the result if they’re configured to."

case text
when ""
#	STDERR.puts('Display Help.') #
	message = {
		"response_type" => "ephemeral",
		"text" => "#{help_header}\n#{help_text}"
	}

	post_message(cgi["response_url"],message)
when /^\/init  *?([1-9]{1}[0-9]?)\+([1-5]{1}(?![0-9])) *(.*?) *$/
#	STDERR.puts("found init: #{text}") #
#	STDERR.puts("Reaction: ", $1) #
#	STDERR.puts("Initiative Dice: ", $2) #
#	STDERR.puts("Comment: ", $3) #

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
		total = $1.to_i + $2.to_i
		roll_string = ''
		for i in 1..$2.to_i
			dieroll = rand(6)
#			STDERR.puts("Rolled: ", die_string[dieroll,1]) #
			roll_string = "#{roll_string}#{die_string[dieroll,1]} "
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
			"attachments" =>
				[
					{
						"color" => "#764FA5",
						"mrkdwn_in" => [ "text" ],
						"callback_id" => "re_init",
						"thumb_url" => chat_icon,
						"fields" =>
							[
								{
									"title" => "Initiative: #{total}",
									"short" => "true"
								},
								{
									"value" => "Reaction #{$1} + #{roll_string}\n",
									"short" => "true"
								}
							],
						"actions" =>
							[
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
	#    Remainder is a comment, capture group 5
when /^(\d{1,2})?(?:\+(\d))?(?: +\[(\d{1,2})\])?(?: +(\d{1,2}))?(?: +(.*?))? *$/
	pool = $1.to_i
	edge = $2.to_i
	edge == 0 && limit = $3.to_i or limit = 100 # Rolled Edge? No Limits
	limit == 0 && limit = 100
	threshold = $4.to_i

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
#			STDERR.puts("POOL ROLL: #{roll}") #
			case rand(6)
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
#			STDERR.puts("EDGE ROLL: #{roll}") #
			case rand(6)
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
				"confirm" =>
					{
						"title" => "#{cc_action} Glitch?",
						"text" => "This will cost you one Edge point.#{reminder}",
						"ok_text" => "Yes",
						"dismiss_text" => "No"
					}
			}
		end

			# Misses are needed for reroller dialogue box
		misses = pool + edge - $hits
		misses != 1 && plural = 'es'
		case
		when ( misses * 3 / 2 ) > pool
			comparison = 'above '
		when ( misses * 3 / 2 ) < pool
			comparison = 'below '
		else
			comparison = ''
		end

			# If Edge was not rolled (no Push the Limits)…
			#    and if there were misses…
			#    and if the limit was not reached…
			#    Then provide a Second Chance!
		STDERR.puts "E:#{edge} M:#{misses} H:#{$hits} L:#{limit}"
#		edge == 0 && misses > 0 && second_chance = {
		edge == 0 && misses > 0 && $hits < limit && second_chance = {
			"name" => "second_chance",
			"text" => "Second Chance…",
			"type" => "button",
			"value" => "#{user_id} #{$hits.to_i} #{misses.to_i} #{threshold.to_i} #{cgc.to_i} #{limit.to_i}",
			"confirm" =>
				{
					"title" => "Reroll #{misses} Miss#{plural}?",
					"text" => "This will cost you one Edge point. #{misses} miss#{plural} is #{comparison}average.", # if that helps you make up your mind.
					"ok_text" => "Yes",
					"dismiss_text" => "No"
				}
		}

			# Test against Limit
		limit > 0 && $hits > limit && $hits = limit

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
			threshold > 0 && detail[detail.length] = "Threshold: #{threshold}"
			limit > 0 && limit < 100 && detail[detail.length] = "Limit: #{limit}"
			threshold_string = "\n#{detail.join(' ')}"
		else
			threshold_string = ''
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
			"attachments" =>
				[
					{
						"thumb_url" => chat_icon,
						"color" => color,
						"fields" =>
							[
								{
									"title" => "#{result}#{critical}#{glitch}",
									"value" => net_string,
									"short" => true
								},
								{
									"value" => "Pool: #{pool} Edge: #{edge}#{threshold_string}",
									"short" => true
								}
							],
						"callback_id" => "edge_effect",
						"actions" =>
							[
#								{
#									"name" => "extended_test",
#									"text" => "Extended Test…",
#									"type" => "button",
#									"value" => "#{user_id} #{$hits} #{pool} #{edge} #{threshold}", # #{interval.to_i}",
#									"confirm" =>
#										{
#											"title" => "Extend Test?",
#											"text" => "This will repeat your roll and keep track of the hits until you hit the threshold.",
#											"ok_text" => "OK",
#											"dismiss_text" => "Cancel"
#										}
#								},
								second_chance,
								cc_button
							]
					}
				]
		}
		post_message(cgi["response_url"],message)

#		STDERR.puts("Hits: #{$hits} Ones: #{ones} Misses: #{misses} #{threshold_string}, #{net_string}") #
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

	cheating = /^((?:[0-9]b)?(?:[0-9]s)?(?:[0-9]a)?(?:[0-9]d)?(?:[0-9]p)?(?:[0-9]c)?(?:[0-9]f)?)(?: +[^\t ].*?)? *$/.match(text)

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
			adv += dice["boost"]["adv"][roll]
			suc += dice["boost"]["suc"][roll]
			sf_roll = 1
		end
		for i in 1..setbk
			roll = rand(6)
			fal += dice["setbk"]["fal"][roll]
			thr += dice["setbk"]["thr"][roll]
			sf_roll = 1
		end
		for i in 1..abilt
			roll = rand(8)
			adv += dice["abilt"]["adv"][roll]
			suc += dice["abilt"]["suc"][roll]
			sf_roll = 1
		end
		for i in 1..dfclt
			roll = rand(8)
			fal += dice["dfclt"]["fal"][roll]
			thr += dice["dfclt"]["thr"][roll]
			sf_roll = 1
		end
		for i in 1..prfnc
			roll = rand(12)
			adv += dice["prfnc"]["adv"][roll]
			suc += dice["prfnc"]["suc"][roll]
			tri += dice["prfnc"]["tri"][roll]
			sf_roll = 1
		end
		for i in 1..chlng
			roll = rand(12)
			fal += dice["chlng"]["fal"][roll]
			thr += dice["chlng"]["thr"][roll]
			des += dice["chlng"]["des"][roll]
			sf_roll = 1
		end
		for i in 1..force
			roll = rand(12)
			drk += dice["force"]["drk"][roll]
			lht += dice["force"]["lht"][roll]
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
			l_or_d = ''
		end

#		STDERR.puts "COL: #{color}  #{s_or_f}  #{a_or_t}  #{t_or_d}" #
			
			# More complete debug, but information that’s displayed anyway.
#		debug = "#{boost}b#{setbk}s#{abilt}a#{dfclt}d#{prfnc}p#{chlng}c#{force}f\n#{success} Success #{failure} Failure #{adv} Advantage #{thr} Threat\n#{tri} Triumph #{des} Despair #{drk} Dark #{lht} Light"
      debug = "#{cheating[1]}\n#{success} Success #{failure} Failure #{adv} Advantage #{thr} Threat"

		message = {
			"response_type" => "in_channel",
			"text" => "*#{sl_user}#{comment}#{iter_comment}*",
			"attachments" =>
				[
					{
						"fallback" => "Star Wars dice roll",
						"color" => color,
						"fields" =>
							[
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
						"footer" => debug,
						"thumb_url" => chat_icon
					}
				]
		}

		post_message(cgi["response_url"],message)
	end
when /^(\d{1,2})?d(\d{1,2}|100|%)([+-]\d{1,2})?(?: +([^\t ].*?))? *$/
		# XdY±Z
	x = $1.to_i
	y = $2.to_i
	z = $3.to_i

	x == 0 && x = 1
	y == 0 && y = 100

		# Delimit comment, if present.
	case $4.to_s
	when ''
		iterations > 1 && comment = " — #" or comment = ''
	else
		iterations > 1 && comment = " — #{$4} #" or comment = " — #{$4}"
	end

	for iteration in 1..iterations
		iterations > 1 && iter_comment = iteration
		total = z
		counter = Hash.new

		for i in 1..x
			roll = rand(y) + 1
#			roll = y # Max Test
#			roll = 1 # Min Test
			counter[roll] = counter[roll].to_i + 1
			total += roll
		end
		STDERR.puts "#{x}d#{y}#{$3} = #{total}#{comment}#{iter_comment}" #
		STDERR.puts counter
		sorted = Hash[counter.sort_by { |key, val| key}]

		message = {
			"response_type" => "in_channel",
			"text" => "*#{sl_user}#{comment}#{iter_comment}*",
			"attachments" =>
				[
					{
						"thumb_url" => chat_icon,
						"color" => "#0000ff",
						"fields" =>
							[
								{
									"title" => total,
									"short" => true
								},
								{
									"value" => "Roll: #{x}d#{y}#{$3.to_s.gsub(/-/,'−')}",
									"short" => true
								}
							],
						"footer" => sorted.to_s 
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
