#!/bin/bash -O extglob
printf 'Content-type: text/html; charset=utf-8\r\nTransfer-Encoding: Chunked\r\n\r\n0\r\n\r\n'
# This is in place to attempt to satisfy Slack’s immediate response requirement.
# Because this is CGI, the client will not actually see this as a chunked request.

# This code for getting code from post data is from
# http://oinkzwurgl.org/bash_cgi and was written by Phillippe Kehi
# <phkehi@gmx.net> and flipflip industries

# (internal) routine to store POST data
function cgi_get_POST_vars()
{
	# check content type
	# FIXME: not sure if we could handle uploads with this..
	[ "${CONTENT_TYPE}" != "application/x-www-form-urlencoded" ] && \
	echo "Warning: you should probably use MIME type "\
		"application/x-www-form-urlencoded!" 1>&2
	# save POST variables (only first time this is called)
	[ -z "$QUERY_STRING_POST" \
		-a "$REQUEST_METHOD" = "POST" -a ! -z "$CONTENT_LENGTH" ] && \
	read -n $((${CONTENT_LENGTH})) QUERY_STRING_POST
	return
}

# (internal) routine to decode urlencoded strings
function cgi_decodevar()
{
	[ $# -ne 1 ] && return
	local v t h
	# replace all + with whitespace and append %%
	t="${1//+/ }%%"
	while [ ${#t} -gt 0 -a "${t}" != "%" ]
	do
		v="${v}${t%%\%*}" # digest up to the first %
		t="${t#*%}"       # remove digested part
		# decode if there is anything to decode and if not at end of string
		if [ ${#t} -gt 0 -a "${t}" != "%" ]
		then
			h=${t:0:2} # save first two chars
			t="${t:2}" # remove these
			v="${v}"$(echo -e \\x${h}) # convert hex to special char
		fi
	done
	# return decoded string. The returned value is
	# exported in cgi_getvars():
	#	export "${k}"="$(cgi_decodevar "${v}")"
	# This method uses “"” so those need escapes.
	echo "${v//\"/\\\"}"
	return
}

# Routine to get variables from http requests
#	usage: cgi_getvars method varname1 [.. varnameN]
# Method is either GET or POST or BOTH
# The magic varible name ALL gets everything
function cgi_getvars()
{
	[ $# -lt 2 ] && return
	local q p k v s
	# get query
	case $1 in
	GET)
		[ ! -z "${QUERY_STRING}" ] && q="${QUERY_STRING}&"
		;;
	POST)
		cgi_get_POST_vars
		[ ! -z "${QUERY_STRING_POST}" ] && q="${QUERY_STRING_POST}&"
		;;
	BOTH)
		[ ! -z "${QUERY_STRING}" ] && q="${QUERY_STRING}&"
		cgi_get_POST_vars
		[ ! -z "${QUERY_STRING_POST}" ] && q="${q}${QUERY_STRING_POST}&"
		;;
	esac
	shift
	s=" $* "
	# parse the query data
	while [ ! -z "$q" ]
	do
		p="${q%%&*}"  # get first part of query string
		k="${p%%=*}"  # get the key (variable name) from it
		v="${p#*=}"   # get the value from it
		q="${q#$p&*}" # strip first part from query string
		# decode and export variable to shell
		[ "$1" = "ALL" -o "${s/ $k /}" != "$s" ] && \
			export "${k}"="$(cgi_decodevar "${v}")"
	done
	return
}

# register all GET and POST variables
cgi_getvars POST ALL

DB_FILE='rpdb'

unauthorized() {
	MESSAGE="$(printf '{"response_type":"ephemeral","text":"Token %s not recognized."}' "${token}")"
	>&2 printf 'Unauthorized token: %s' "${token}"
}

readonly token="$(printf '%.24s' "${token//[^A-Za-z0-9]}")"

case "${token}" in
"$(sqlite3 "${DB_FILE}" "SELECT DISTINCT token FROM tokens WHERE token IS \"${token}\"")")
		# Sanitize channel_id, user_id
	channel_id="$(printf '%.9s' "${channel_id//[^A-Za-z0-9]}")"

	user_id="${user_id//[^A-Za-z0-9]}"
	user_id="$(printf 'U%.8s' "${user_id#?}")"

	open_config() {
		declare -i DB_CONFIG=$(sqlite3 "${DB_FILE}" "SELECT config FROM channels WHERE channel IS \"${channel_id}\" LIMIT 1")
		readonly DB_CONFIG="${DB_CONFIG:-0}"
		readonly GAME="$(sqlite3 "${DB_FILE}" "SELECT game FROM global WHERE config IS ${DB_CONFIG} LIMIT 1")"
		readonly PREFIX="$(sqlite3 "${DB_FILE}" "SELECT prefix FROM online WHERE config IS ${DB_CONFIG} LIMIT 1")"
		readonly SUFFIX="$(sqlite3 "${DB_FILE}" "SELECT suffix FROM online WHERE config is ${DB_CONFIG} LIMIT 1")"
		readonly ONLINE_COMMAND="$(sqlite3 "${DB_FILE}" "SELECT command FROM online WHERE config IS ${DB_CONFIG} LIMIT 1")"
		readonly ONLINE_NAME="$(sqlite3 "${DB_FILE}" "SELECT name FROM online WHERE config IS ${DB_CONFIG} LIMIT 1")"
		readonly ONLINE_ICON="$(sqlite3 "${DB_FILE}" "SELECT icon FROM online WHERE config IS ${DB_CONFIG} LIMIT 1")"
		readonly ONLINE_PROG="$(sqlite3 "${DB_FILE}" "SELECT program FROM online WHERE config IS ${DB_CONFIG} LIMIT 1")"
		readonly CHAT_HOOK="$(sqlite3 "${DB_FILE}" "SELECT chat_hook FROM global WHERE config IS ${DB_CONFIG} LIMIT 1")"
		NAME_PATTERN=($(echo -n $(sqlite3 "${DB_FILE}" "SELECT DISTINCT charname FROM characters WHERE config IS ${DB_CONFIG} AND slack_user IS NOT \"${user_id}\" and GM is null"|awk '{print $1}')))
		PATTERN_USER=($(echo -n $(sqlite3 "${DB_FILE}" "SELECT DISTINCT slack_user FROM characters WHERE config IS ${DB_CONFIG} AND slack_user IS NOT \"${user_id}\" and GM is null")))

			# Get the character name and GM authorization.
		SL_USER="$(sqlite3 "${DB_FILE}" \
			"SELECT charname FROM characters WHERE config IS ${DB_CONFIG} AND slack_user IS \"${user_id}\" LIMIT 1")"
		readonly GM_AUTH="$(sqlite3 "${DB_FILE}" \
			"SELECT GM FROM characters WHERE config IS ${DB_CONFIG} AND slack_user IS \"${user_id}\" LIMIT 1")"

			# If no character name was found, use the player name and complain, unless it’s
			# in a directmessage channel, then someone’s just rolling their own dice.
		case "${SL_USER}" in
		'')
			SL_USER="${user_name}"
			[ "${channel_name}" != "directmessage" ] && [ "${channel_name}" != "privategroup" ] && >&2 printf 'Unconfigured ID %s (%s) in %s (%s)' "${user_id}" "${user_name}" "${channel_id}" "${channel_name}"
			exit
			;;
		esac

		NAME_ARRAY=( ${SL_USER} )

			# Gather the channel icons, setting reasonable defaults.
		CHAT_ICON="$(sqlite3 "${DB_FILE}" \
			"select picture from characters where config is ${DB_CONFIG} and slack_user is \"${user_id}\";")"
		DEFAULT_ICON="$(sqlite3 "${DB_FILE}" "select default_icon from global where config is ${DB_CONFIG};")"
			# Default game icon if no avatar
		CHAT_ICON="${CHAT_ICON:-${DEFAULT_ICON}}"
	}

		# Configure
	open_config "${channel_id}"
	readonly HELP_HEADER="*${GAME} Utility v${0//+(*??_|.cgi)} in-line help*\n"
	declare -ri EPOCH=$(date -j +%s)

	logger() {
		printf '%s\n' "${*}" >> "chat_logs/${channel_name#\#}"
	}

	mention() {
		for ((ace=0;ace<${#NAME_PATTERN[@]};ace++))
		do
			[[ "${*}" == *"${NAME_PATTERN[$ace]}"* ]] && curl -X POST --url "${response_url}" --silent --fail --data "{\"username\":\"RPG\",\"icon_emoji\":\":game_die:\",\"response_type\":\"ephemeral\",\"text\":\"${NAME_PATTERN[$ace]} was mentioned by ${SL_USER% *} in <#${channel_id}|${channel_name}>.\",\"channel\":\"${PATTERN_USER[$ace]}\"}" &> /dev/null &
# 			This seems to be working as expected, so I’m turning off
#			the logging/debugging code for now.
#			[[ "${*}" == *"${NAME_PATTERN[$ace]}"* ]] && >&2 printf '%s mentioned by %s in %s\nNotifying %s' "${NAME_PATTERN[$ace]}" "${SL_USER% *}" "${channel_name}" "${PATTERN_USER[$ace]}" &
		done
	}

	matrix_format() {
			[ -f "online_progs/${ONLINE_PROG}" ] && \
				[ -x "online_progs/${ONLINE_PROG}" ] && \
				ONLINE_TEXT="$(online_progs/${ONLINE_PROG} ${user_id} $(printf '%s' "${SL_USER}"|base64 -) $(printf '%s' "${*}"|base64 -))" || \
				ONLINE_TEXT="\`${PREFIX}${*//\`}${SUFFIX}${NAME_ARRAY[0]} <${EPOCH}>\`"
	}

	matrix() {
		if [ ${#*} -ne 0 ]
		then
			response_url="${CHAT_HOOK}"
			RESPONSE='in_channel'
			matrix_format "${*}"
			MESSAGE="$(printf '{"username":"%s","attachments":[{"footer":"%s"}],"icon_url":"%s","text":"%s","channel":"%s"}' \
				"${ONLINE_NAME}" "${PRIVTOKEN}" "${ONLINE_ICON}" "${ONLINE_TEXT}" "${channel_id}")"

			mention "${ONLINE_TEXT}" &
			logger "${ONLINE_TEXT} ${PRIVTOKEN}"
		else
			matrix_format 'We have trouble inbound!'
			MESSAGE="$(printf '{"response_type":"ephemeral","text":"%s`%s` formats your message as an online message. For example, `%s We have trouble inbound!` looks like this:","attachments":[{"text":"%s","author_icon":"%s","author_name":"%s","mrkdwn_in":["text"]}]}' "${HELP_HEADER}" "${SLASH}" "${SLASH}" "${ONLINE_TEXT}" "${ONLINE_ICON}" "${ONLINE_NAME}")"
		fi
	}

	chatter() {
		response_url="${CHAT_HOOK}"
		RESPONSE='in_channel'
		MESSAGE="$(printf '{"username":"%s","icon_url":"%s","text":"%s","channel":"%s","attachments":[{"footer":"%s"}]}' "${SL_USER}" "${CHAT_ICON}" "$text" "${channel_id}" "${PRIVTOKEN}")"

		mention "${text}" &
		logger "*${SL_USER}*: $text ${PRIVTOKEN}"
	}

	meatspace() {
		text="${ARGUMENTS[@]}"
		if [ ${#text} -ne 0 ]
		then
			response_url="${CHAT_HOOK}"
			RESPONSE='in_channel'

				# Since bold and italics are used in formatting the
				# message, remove them.
			text="${text//[*_]}"
				# Replace instances of EMOTE with actor’s name.
			text="${text//${EMOTE}/${NAME_ARRAY[0]}}"
				# Attempt to highlight all occurrences of the actor’s name.
			text="${text// ${NAME_ARRAY[0]}/ *${NAME_ARRAY[0]}*}"

				# Attempt to highlight all occurrences of any character name.
			for ((ace=0;ace<${#NAME_PATTERN[@]};ace++))
			do
				text="${text// ${NAME_PATTERN[$ace]}/ *${NAME_PATTERN[$ace]}*}"
			done
			mention "${text}" &

			MESSAGE="$(printf '{"username":"­","attachments":[{"footer":"%s"}],"icon_url":"%s","text":"_*%s* %s_","channel":"%s"}' "${PRIVTOKEN}" "${DEFAULT_ICON}" "${NAME_ARRAY[0]}" "${text}" "${channel_id}")"
			logger "*${NAME_ARRAY[0]}* ${text} ${PRIVTOKEN}"
		else
			MESSAGE="$(printf '{"response_type":"ephemeral","text":"%s`%s` formats your message as an emote. For example, `%s smirks.` looks like this:","attachments":[{"text":"_*%s* smirks._","author_icon":"%s","mrkdwn_in":["text"]}]}' "${HELP_HEADER}" "${SLASH}" "${SLASH}" "${NAME_ARRAY[0]}" "${DEFAULT_ICON}")"
		fi
	}

	RESPONSE='ephemeral'

		# command tokens: If people want the command to be 'filibuster'
		# instead of 'roll', they are insane, but the change is here.
		# Help files reference these, too.
	readonly REROLL_INIT_TOKEN='/reinit'
	readonly INITIATIVE_TOKEN='/init'
	readonly ROLL_COMMAND='/roll'
	readonly GM_COMMAND='/gm'
	readonly PRIVMSG_TOKEN='/msg'
	readonly EMOTE='/me'

	readonly DICE_EMOJI=( ⚀ ⚁ ⚂ ⚃ ⚄ ⚅ )

	ARGUMENTS=( ${text} )

		# Send message to a user
	case "${ARGUMENTS[0]}" in
	"${PRIVMSG_TOKEN}")
		PRIVTOKEN="from <#${channel_id}|${channel_name}> player <@${user_id}|${user_name}> to ${ARGUMENTS[1]}"
		channel_id="${ARGUMENTS[1]}"
		text="${ARGUMENTS[@]:2}"
		ARGUMENTS=( ${text} )
		PRIVMSG='TRUE'
		;;
	esac

	readonly SUBCOMMAND="${ARGUMENTS[0]}"
	SLASH="$(printf '%s %s' "${command}" "${SUBCOMMAND}")"
	unset ARGUMENTS[0]

	case "${SUBCOMMAND}" in
	"${ONLINE_COMMAND}")
		matrix "${ARGUMENTS[@]}"
		;;
	"${ROLL_COMMAND}"?([1-9]))
		declare -i ITERATIONS=$((${SUBCOMMAND#${ROLL_COMMAND}}))
		[ $((${ITERATIONS})) -eq 0 ] && declare -i ITERATIONS=1
		SLASH="$(printf '%s %s' "${command}" "${SUBCOMMAND%${ITERATIONS}}")"

		case $GM_AUTH in
		'GM')
			GM_ROLL_MESSAGE="$(printf '\n\nAs an authorized GM, you can use the keywords “/max” and “/min” with the NdX±Y dice roller to roll fixed maximum or minimum rolls, respectively, e.g., `%s %s 3d6+2 /max Bad guy punch damage` will always generate 20 accompanied by the message “*Bad guy punch damage*”. The keyword “/force” followed by a number will always roll that number, e.g. `%s %s d100 /force 97` will always roll 97.' \
			"${command}" "${ROLL_COMMAND}" \
			"${command}" "${ROLL_COMMAND}")"
			;;
		esac

		ROLL_HELP="$(printf '`%s` accepts several dice roll types:\n\n*1.* Roll a pool of the format `d+e`, e.g. `%s 5+3`, where 5 is your pool size and 3 is your edge dice.  You can omit either, but not both, e.g. `%s 5` or `%s +2`. This type also accepts an optional threshold, e.g. `%s 10+2 3`.\n\nThe color of the sidebar will be green if you rolled hits, yellow if you didn’t, and red if you glitched.  If a threshold was supplied, green indicates success, yellow indicates failure, and red indicates a glitch.\n\n*2.* Roll the more standard gaming format of `NdX±Y`, e.g. `%s 4d6+2`, `3d8-2`, or `d100`. Omitting the number of dice to roll defaults to 1 rolled die.\n\n*3.* Roll a Shadowrun initiative roll using the format `r+p`, e.g. `%s %s 9+4`, where 9 is your reaction a 4 is your effective dice pool.\n\n*4.* Re-roll a Shadowrun initiative roll using the format `i±p`, e.g. `%s %s 22-3`, where 22 is your current initiative and 3 is the number of dice by which your initiative is to be reduced.\n\n*5.* Roll a Star Wars Boost, Setback, Ability, Difficulty, Proficiency, Challenge, and Force roll using the format `#b#s#a#d#p#c#f`. Each element is optional, but the order is strict.  For example, you can roll 2b3a1p for 2 Boost, 3 Ability, 1 Proficiency, but they *must* be in the order specified.\n\n*You can now roll dice privately in your own direct message channel, and `%s` _will not complain!_* This keeps it visible only to you and lets bots interact with the result if they’re configured to.\n\nAny of those will accept, after the roll syntax, a comment to help identify the roll’s purpose, e.g. `%s 4+2 Bad Guy #1 Dodge`.\n\nSome rolls, where sensible, allow an iterator; typing a number between 1 and 9 immediately after %s, e.g. `%s3 4 2 Attack`, will cause that number of rolls to be made. A number will be appended to any comment.\n\n*HINT:* Tab repeats the last command, and many rolls will accept 0 as a number of dice to roll. For more complex rolls, specify zero dice in the unused fields and a tab-edit makes the roller easier to use. For example: `%s 1b0s2a2d1p0c0f`%s' "${SLASH}" "${SLASH}" "${SLASH}" "${SLASH}" "${SLASH}" "${SLASH}" "${SLASH}" "${INITIATIVE_TOKEN}" "${SLASH}" "${REROLL_INIT_TOKEN}" "${SLASH}" "${SLASH}" "${SLASH}" "${SLASH}" "${GM_ROLL_MESSAGE}")"
		text="${ARGUMENTS[@]}"

		RESPONSE='in_channel'

			# Process various roll types.  First, no text, provide help.
		case "${text}" in
		'')
			MESSAGE="$(printf '{"response_type":"ephemeral","text":"%s%s"}' "${HELP_HEADER}" "${ROLL_HELP}")"
			curl -X POST -H 'Content-type: application/json' --url "${response_url}" --silent --fail --data "${MESSAGE}" &> /dev/null
			;;
		?(+([0-9])b)?(+([0-9])s)?(+([0-9])a)?(+([0-9])d)?(+([0-9])p)?(+([0-9])c)?(+([0-9])f)?( *))
			# Boost, Setback, Ability, Difficulty, Proficiency, Challenge, Force
			readonly BOOST_ADV=( 0 0 2 1 1 0 )
			readonly BOOST_SUC=( 0 0 0 0 1 1 )
			readonly SETBK_FAL=( 0 0 1 1 0 0 )
			readonly SETBK_THR=( 0 0 0 0 1 1 )
			readonly ABILT_ADV=( 0 0 0 0 1 1 1 2 )
			readonly ABILT_SUC=( 0 1 1 2 0 0 1 0 )
			readonly DFCLT_FAL=( 0 1 2 0 0 0 0 1 )
			readonly DFCLT_THR=( 0 0 0 1 1 1 2 1 )
			readonly PRFNC_ADV=( 0 0 0 0 0 1 1 1 1 2 2 0 )
			readonly PRFNC_SUC=( 0 1 1 2 2 0 1 1 1 0 0 0 )
			readonly PRFNC_TRI=( 0 0 0 0 0 0 0 0 0 0 0 1 )
			readonly CHLNG_FAL=( 0 1 1 2 2 0 0 1 1 0 0 0 )
			readonly CHLNG_THR=( 0 0 0 0 0 1 1 1 1 2 2 0 )
			readonly CHLNG_DES=( 0 0 0 0 0 0 0 0 0 0 0 1 )
			readonly FORCE_DRK=( 1 1 1 1 1 1 2 0 0 0 0 0 )
			readonly FORCE_LHT=( 0 0 0 0 0 0 0 1 1 2 2 2 )

			AM_I_CHEATING=( ${text} )
			PRE_ITER_text="${text}"

			for ((ITERATION=1;${ITERATION}<=${ITERATIONS};ITERATION++))
			do
				[ ${ITERATIONS} -gt 1 ] && ITER_COMMENT=" #${ITERATION}" || unset ITER_COMMENT
				declare -i ADV=0 SUC=0 FAL=0 THR=0 TRI=0 DES=0 DRK=0 LHT=0 SF_ROLL=0 SW_VALUE=0
				text="${PRE_ITER_text}"

				for SPLIT in b s a d p c f
				do
					case "${text}" in
					+([0-9])b?(*))
						SW_STR=( ${text/b/ } )
						for ((i=0;i<${SW_STR[0]};i++))
						do
							ROLL=$((${RANDOM}%6))
							ADV=$((${ADV}+${BOOST_ADV[${ROLL}]}))
							SUC=$((${SUC}+${BOOST_SUC[${ROLL}]}))
							SF_ROLL=1
						done
						;;
					+([0-9])s?(*))
						SW_STR=( ${text/s/ } )
						text="${SW_STR[1]}"
						for ((i=0;i<${SW_STR[0]};i++))
						do
							ROLL=$((${RANDOM}%6))
							FAL=$((${FAL}+${SETBK_FAL[${ROLL}]}))
							THR=$((${THR}+${SETBK_THR[${ROLL}]}))
							SF_ROLL=1
						done
						;;
					+([0-9])a?(*))
						SW_STR=( ${text/a/ } )
						text="${SW_STR[1]}"
						for ((i=0;i<${SW_STR[0]};i++))
						do
							ROLL=$((${RANDOM}%8))
							ADV=$((${ADV}+${ABILT_ADV[${ROLL}]}))
							SUC=$((${SUC}+${ABILT_SUC[${ROLL}]}))
							SF_ROLL=1
						done
						;;
					+([0-9])d?(*))
						SW_STR=( ${text/d/ } )
						text="${SW_STR[1]}"
						for ((i=0;i<${SW_STR[0]};i++))
						do
							ROLL=$((${RANDOM}%8))
							FAL=$((${FAL}+${DFCLT_FAL[${ROLL}]}))
							THR=$((${THR}+${DFCLT_THR[${ROLL}]}))
							SF_ROLL=1
						done
						;;
					+([0-9])p?(*))
						SW_STR=( ${text/p/ } )
						text="${SW_STR[1]}"
						for ((i=0;i<${SW_STR[0]};i++))
						do
							ROLL=$((${RANDOM}%12))
							ADV=$((${ADV}+${PRFNC_ADV[${ROLL}]}))
							SUC=$((${SUC}+${PRFNC_SUC[${ROLL}]}))
							TRI=$((${TRI}+${PRFNC_TRI[${ROLL}]}))
							SF_ROLL=1
						done
						;;
					+([0-9])c?(*))
						SW_STR=( ${text/c/ } )
						text="${SW_STR[1]}"
						for ((i=0;i<${SW_STR[0]};i++))
						do
							ROLL=$((${RANDOM}%12))
							FAL=$((${FAL}+${CHLNG_FAL[${ROLL}]}))
							THR=$((${THR}+${CHLNG_THR[${ROLL}]}))
							DES=$((${DES}+${CHLNG_DES[${ROLL}]}))
							SF_ROLL=1
						done
						;;
					+([0-9])f?(*))
						SW_STR=( ${text/f/ } )
						text="${SW_STR[1]}"
						for ((i=0;i<${SW_STR[0]};i++))
						do
							ROLL=$((${RANDOM}%12))
							DRK=$((${DRK}+${FORCE_DRK[${ROLL}]}))
							LHT=$((${LHT}+${FORCE_LHT[${ROLL}]}))
						done
						;;
					esac
					unset SW_STR[0]
					text="${SW_STR[@]}"
				done

				COMMENT="${text}"	# Remainder is the comment

					# If a comment is present, add some formatting, otherwise
					# (over-cautiously) ensure that it’s an empty string.
				[ ${#COMMENT} -gt 0 ] && COMMENT=" — ${COMMENT}" || COMMENT=''

				declare -i SUCCESS=$((${SUC}+${TRI}))
				declare -i FAILURE=$((${FAL}+${DES}))

				COLOR='#764FA5'
				S_OR_F=''
				A_OR_T=''
				T_OR_D=''
				FORCE=''

				case $SF_ROLL in
				1)
					[ ${SUCCESS} -gt ${FAILURE} ] && SF_RESULT="S" || SF_RESULT="F"
					case "${SF_RESULT}" in
					S)
						COLOR='good'
						SW_VALUE=$((${SUCCESS}-${FAILURE}))
						[ ${SW_VALUE} -ne 1 ] && S_OR_F="${SW_VALUE} Successes" || S_OR_F='1 Success'
						[ ${DES} -gt 0 ] && COLOR='warning'
						;;
					F)
						COLOR='warning'
						SW_VALUE=$((${FAILURE}-${SUCCESS}))
						[ ${SW_VALUE} -ne 1 ] && S_OR_F="${SW_VALUE} Failures" || S_OR_F='1 Failure'
						[ ${SW_VALUE} -eq 0 ] && S_OR_F='Failure'
						[ ${DES} -gt 0 ] && COLOR='danger'
						;;
					esac
					;;
				esac

				[ ${ADV} -gt ${THR} ] && A_OR_T="$((${ADV}-${THR})) Advantage"
				[ ${THR} -gt ${ADV} ] && A_OR_T="$((${THR}-${ADV})) Threat"

				[ ${TRI} -gt 0 ] && T_OR_D=( ${T_OR_D[@]} "${TRI} Triumph" )
				[ ${DES} -gt 0 ] && T_OR_D=( ${T_OR_D[@]} "${DES} Despair" )
				[ ${#T_OR_D} -gt 0 ] && T_OR_D="${T_OR_D[@]}"

				[ ${DRK} -gt 0 ] && FORCE=( ${FORCE[@]} "${DRK} Dark" )
				[ ${LHT} -gt 0 ] && FORCE=( ${FORCE[@]} "${LHT} Light" )
				[ ${#FORCE} -gt 0 ] && FORCE="${FORCE[@]}"

					# If the roll is Force-only, left justify.
				[ ${SF_ROLL} -eq 0 ] && S_OR_F=${FORCE} && unset FORCE

				DEBUG="\n${SUCCESS} Success ${FAILURE} Failure ${ADV} Advantage ${THR} Threat\n${TRI} Triumph ${DES} Despair ${DRK} Dark ${LHT} Light"

				MESSAGE="$(printf '{"response_type":"%s","text":"*%s%s%s*","attachments":[{"fallback":"Star Wars dice roll","color":"%s","fields":[{"title":"%s","value":"%s","short":true},{"title":"%s","value":"%s","short":true}],"footer":"%s%s","thumb_url":"%s"}]}' "${RESPONSE}" "${SL_USER}" "${COMMENT}" "${ITER_COMMENT}" "${COLOR}" "${S_OR_F}" "${A_OR_T}" "${FORCE}" "${T_OR_D}" "${AM_I_CHEATING[0]}" "${DEBUG}" "${CHAT_ICON}")"
				curl -X POST -H 'Content-type: application/json' --url "${response_url}" --silent --fail --data "${MESSAGE}" &> /dev/null
			done
			;;
		"${REROLL_INIT_TOKEN} "+([0-9])[+-]+([0-9])?( *))	# Test case for initiative reroll
			DICE_STRING=''
			declare -i TOTAL ROLL REINIT_ELEMENT
			text=( ${text:${#REROLL_INIT_TOKEN}} )
			XY="${text[0]}"		# Collect X±Y into XY
			unset text[0]
			COMMENT="${text[@]}"	# Remainder is the comment

				# If a comment is present, add some formatting, otherwise
				# (over-cautiously) ensure that it’s an empty string.
			[ ${#COMMENT} -gt 0 ] && COMMENT=" — ${COMMENT}" || COMMENT=''

			REINIT_ELEMENT=( ${XY//[+-]/ } )	# Split X±Y into X and Y
			TOTAL=${REINIT_ELEMENT[0]}		# Initialize the TOTAL to starting Initiative (X)

			case "${XY}" in
			+([0-9])-+([0-9]))		# −Y…
				MATH_OP='-'
				;;
			+([0-9])++([0-9]))		# … +Y…
				MATH_OP='+'
				;;
			esac

			for ((i=0;i<${REINIT_ELEMENT[1]};i++))
			do
				ROLL=$((${RANDOM}%6))
				DICE_STRING="${DICE_STRING} ${DICE_EMOJI[${ROLL}]}"
				TOTAL=$((${TOTAL}${MATH_OP}${ROLL}))
			done
			TOTAL=$((${TOTAL}${MATH_OP}${REINIT_ELEMENT[1]}))

			DICE_STRING=( ${DICE_STRING} )
			DICE_STRING="${DICE_STRING[@]}"

			MESSAGE="$(printf '{"response_type":"%s","text":"*%s%s*","attachments":[{"color":"#764FA5","fields":[{"title":"Initiative: %d","short":true},{"value":"Initiative %d %s %s","short":true}],"mrkdwn_in":["text"],"thumb_url":"%s"}]}' "${RESPONSE}" "${SL_USER}" "${COMMENT}" "${TOTAL}" "${REINIT_ELEMENT[0]}" "${MATH_OP/-/−}" "${DICE_STRING}" "${CHAT_ICON}")"
			[ $((${ITERATIONS})) -le 1 ] && curl -X POST -H 'Content-type: application/json' --url "${response_url}" --silent --fail --data "${MESSAGE}" &> /dev/null &
			;;
		"${INITIATIVE_TOKEN} "+([0-9])++([0-9])?( *))	# Test case for initiative
			text=( ${text:${#INITIATIVE_TOKEN}} )
			XY=( ${text[0]//+/ } )
			unset text[0]
			COMMENT="${text[@]}"

			[ ${#COMMENT} -gt 0 ] && COMMENT=" — ${COMMENT}"

			for ((ITERATION=1;${ITERATION}<=${ITERATIONS};ITERATION++))
			do
				[ ${ITERATIONS} -gt 1 ] && ITER_COMMENT=" #${ITERATION}" || unset ITER_COMMENT
				DICE_STRING=''
				declare -i TOTAL=0 ROLL

				for ((i=0;i<${XY[1]};i++))
				do
					ROLL=$((${RANDOM}%6))
					DICE_STRING="${DICE_STRING} ${DICE_EMOJI[${ROLL}]}"
					TOTAL=$((${TOTAL}+${ROLL}))
				done

				TOTAL=$((${TOTAL}+${XY[0]}+${XY[1]}))
				DICE_STRING=( ${DICE_STRING} )
				DICE_STRING="${DICE_STRING[@]}"

				REINIT_STATE="${user_id} ${TOTAL} 0"
				RE_INIT="$(printf ',"callback_id":"re_init","actions":[{"style":"primary","name":"up_stat","text":"+1","type":"button","value":"%s"},{"style":"danger","name":"dn_stat","text":"−1","type":"button","value":"%s"},{"style":"primary","name":"up_init","text":"+🎲","type":"button","value":"%s"},{"style":"danger","name":"dn_init","text":"−🎲","type":"button","value":"%s"}]' "${REINIT_STATE}" "${REINIT_STATE}" "${REINIT_STATE}" "${REINIT_STATE}" )"

				MESSAGE="$(printf '{"response_type":"%s","text":"*%s%s%s*","attachments":[{"color":"#764FA5","fields":[{"title":"Initiative: %d","short":true},{"value":"Reaction %d + %s\n","short":true}],"mrkdwn_in":["text"],"thumb_url":"%s"%s}]}' \
				"${RESPONSE}" "${SL_USER}" "${COMMENT}" "${ITER_COMMENT}" "${TOTAL}" "${XY[0]}" "${DICE_STRING}" \
				"${CHAT_ICON}" "${RE_INIT}")"
				curl -X POST -H 'Content-type: application/json' --url "${response_url}" --silent --fail --data "${MESSAGE}" &> /dev/null
			done
			;;
		*([0-9])?(+*([0-9]))?( +([0-9]))?( *))	# Test case for pool+edge roller
			INPUT=( ${text} )			# Initial tokenization
			declare -ri POOL=${INPUT[0]%%+*}  # left of +
			declare -ri EDGE=$((${INPUT[0]}-${POOL})) # do math and subtract POOL
			declare -ri THRESHOLD=$((${INPUT[1]//[^0-9]}))

			[ ${THRESHOLD} -gt 0 ] && STRIP=2 || STRIP=1
			COMMENT="${INPUT[@]:${STRIP}}"
			COMMENT="${COMMENT//[*]}"
			[ ${#COMMENT} -gt 0 ] && COMMENT=" — ${COMMENT}" || COMMENT=''

				# Explosion subroutine, recursing, adding hits, ignoring 1s.
			explosion() {
				case $((${RANDOM}%6)) in
				4)
					HIT=$((${HIT}+1))
					;;
				5)
					HIT=$((${HIT}+1))
					explosion		# By probability alone is an endless loop avoided…
					;;
				esac
			}

			for ((ITERATION=1;${ITERATION}<=${ITERATIONS};ITERATION++))
			do
				[ ${ITERATIONS} -gt 1 ] && ITER_COMMENT=" #${ITERATION}" || unset ITER_COMMENT
				COLOR='good'
				declare -i HIT=0 ONES=0 NET=0 ROLL

				for ((i=0;i<${POOL};i++))
				do
					case $((${RANDOM}%6)) in
					0)
						ONES=$((${ONES}+1))
						;;
					4)
						HIT=$((${HIT}+1))
						;;
					5)
						HIT=$((${HIT}+1))
						[ ${EDGE} -gt 0 ] && explosion	# Invoke Rule of Six if Edge was supplied
						;;
					esac
				done

				for ((i=0;i<${EDGE};i++))
				do
					case $((${RANDOM}%6)) in
					0)
						ONES=$((${ONES}+1))
						;;
					4)
						HIT=$((${HIT}+1))
						;;
					5)
						HIT=$((${HIT}+1))
						explosion					# Edge dice, so Rule of Six always applies
						;;
					esac
				done

				if [ ${THRESHOLD} -gt 0 ]		# If threshold is known, give a pretty response
				then
					if [ ${HIT} -ge ${THRESHOLD} ]
					then
						NET=$((${HIT}-${THRESHOLD}))
						RESULT="Success! "
						[ ${NET} -ne 1 ] && NET_STRING="${NET} Net Hits." || NET_STRING='1 Net Hit.'
					else
						RESULT='Failure.'
						COLOR='warning'
					fi
				else
					[ ${HIT} -ne 1 ] && RESULT="${HIT} Hits." || RESULT='1 Hit.'
					[ ${HIT} -eq 0 ] && COLOR='warning'
				fi

#				>&2 printf 'Ones: %d' ${ONES}
				if [ ${ONES} -gt $(($((${INPUT[0]}))/2)) ]	# Show (critical) glitch
				then
					CGC=1
					GLITCH=' Glitch!'
					COLOR='danger'
					[ ${HIT} -eq 0 ] && CRITICAL=' Critical' && COLOR='000000' && CGC=2
					[ ${EDGE} -eq 0 ] && CC_BUTTON="$(printf '{"name":"close_call","text":"Close Call","type":"button","value":"%s","confirm":{"title":"Downgrade Glitch?","text":"This will cost you one Edge point.","ok_text":"Yes","dismiss_text":"No"}}' "${COLOR}")"
				fi

				declare -i MISSES=$((${POOL}+${EDGE}-${HIT}))
#				SHORTFALL=$((${THRESHOLD}-${HIT}))
#				[ ${SHORTFALL} -gt 0 ] || unset SHORTFALL

				[ ${MISSES} -eq 1 ] || PLURAL="es"

					# If Edge was not rolled, a Second Chance might be allowed.

					# Defined here because I am doing this in bash, not really building
					# JSON as a hash or anything, but just making a string. I give Slack
					# something to parse.
				COMPARISON=''
				[ $((${MISSES}*3/2)) -lt $((${POOL})) ] && COMPARISON="below "
				[ $((${MISSES}*3/2)) -gt $((${POOL})) ] && COMPARISON="above "
				SECOND_CHANCE='{"name":"no_roll"}'
				[ ${EDGE} -eq 0 ] && [ ${MISSES} -gt 0 ] && SECOND_CHANCE="$(printf '{"name":"second_chance","text":"Second Chance","type":"button","value":"%s","confirm":{"title":"Reroll %s Misses?","text":"This will cost you one Edge point. %d misses is %saverage if that helps you make up your mind.","ok_text":"Yes","dismiss_text":"No"}}'\
					"$(printf '%s %d %d %d %d' ${user_id} ${HIT} ${MISSES} ${THRESHOLD} ${CGC})" \
					${MISSES} ${MISSES} "${COMPARISON}")"
#					>&2 printf '%s %d %d %d %d' ${user_id} ${HIT} ${MISSES} ${THRESHOLD} ${CGC}

				if [ $((${POOL}+${EDGE})) -ne 0 ]
				then
					[ ${THRESHOLD} -gt 0 ] && THRESHOLD_STRING="\nThreshold: ${THRESHOLD}" || THRESHOLD_STRING=''
					MESSAGE="$(printf '{"response_type":"%s","text":"*%s%s%s*","attachments":[{"thumb_url":"%s","color":"%s","fields":[{"title":"%s%s%s","value":"%s","short":true},{"value":"Pool: %d Edge: %d%s","short":true}],"callback_id":"edge_effect","actions":[%s,%s]}]}' "${RESPONSE}" "${SL_USER}" "${COMMENT}" "${ITER_COMMENT}" "${CHAT_ICON}" "${COLOR}" "${RESULT}" "${CRITICAL}" "${GLITCH}" "${NET_STRING}" ${POOL} ${EDGE} "${THRESHOLD_STRING}" "${SECOND_CHANCE}" "${CC_BUTTON}")"
				else
					MESSAGE="$(printf '{"response_type":"ephemeral","text":"%sThe syntax for this `%s` type requires a pool of the format `d+e`, e.g. `%s 5+3`, where 5 is your pool size and 3 is your edge dice.  You can omit either, but not both, e.g. `%s 5` or `%s +2`.\n\nThis `%s` type also accepts an optional threshold, e.g. `%s 10+2 3`\n\nThe color of the sidebar will be green if you rolled hits, yellow if you rolled no hits, and red or black if you glitched (black meaning a critical glitch).  If a threshold was supplied, green indicates success, yellow indicates failure, and red indicates a glitch."}' "${HELP_HEADER}" "${SLASH}" "${SLASH}" "${SLASH}" "${SLASH}" "${SLASH}" "${SLASH}")"
					ITERATION=${ITERATIONS}
				fi
				curl -X POST -H 'Content-type: application/json' --url "${response_url}" --silent --fail --data "${MESSAGE}" &> /dev/null
			done
			;;
		?([1-9]*([0-9]))d[1-9]*([0-9])?([+-][1-9]*([0-9]))?( *))	# Test case for NdX±Y

			# If N is absent, assume single die, e.g. d6 = 1d6
			[ ${text:0:1} == "d" ] && text="1${text}"

			NdX=( ${text//d/ } )	# Split NdX±Y into N and X±Y
			REQUEST="$(printf 'Roll %dd%s' ${NdX[0]} ${NdX[1]})"
			XY=( ${NdX[1]//[+-]/ } )	# Split X±Y into X and Y

			# Treat the + or - as a token, and create the number to add.
			case ${NdX[1]} in
			+([0-9])-+([0-9]))		# −Y…
				FUDGE=$((0-${XY[1]}))
				;;
			+([0-9])++([0-9]))		# … +Y…
				FUDGE=$((0+${XY[1]}))
				;;
			*)					# … or Y=0.
				FUDGE=0
				;;
			esac

			COMMENT=( ${text} )

			unset COMMENT[0]
			[ ${#COMMENT[@]} -gt 0 ] && COMMENT=" — ${COMMENT[@]}" || COMMENT=''

			for ((ITERATION=1;${ITERATION}<=${ITERATIONS};ITERATION++))
			do
				[ ${ITERATIONS} -gt 1 ] && ITER_COMMENT=" #${ITERATION}" || unset ITER_COMMENT
				declare -i TOTAL=0
				unset COUNT COUNT_STRING

				case "${GM_AUTH} ${COMMENT[1]}" in
				"GM /force")
					unset COMMENT[1]
					>&2 printf 'GM force roll'
					for ((i=0;i<$((${NdX[0]}));i++))
					do
						ROLL=$((${COMMENT[2]}))
						TOTAL=$((${TOTAL}+${ROLL}))
						COUNT[${ROLL}]=$((${COUNT[${ROLL}]}+1))
					done
					TOTAL=$((${TOTAL}+${FUDGE}))
					unset COMMENT[2]
					;;
				"GM /max")
					unset COMMENT[1]
					TOTAL=$((${XY[0]}*${NdX[0]}+${FUDGE}))
					>&2 printf 'GM high roll'
					COUNT[${XY[0]}]=${NdX[0]}
					;;
				"GM /min")
					unset COMMENT[1]
					TOTAL=$((${NdX[0]}+${FUDGE}))
					>&2 printf 'GM low roll'
					COUNT[1]=${NdX[0]}
					;;
				*)
					for ((i=0;i<$((${NdX[0]}));i++))
					do
						ROLL=$((${RANDOM}%$((${XY[0]}))+1))
						TOTAL=$((${TOTAL}+${ROLL}))
						COUNT[${ROLL}]=$((${COUNT[${ROLL}]}+1))
					done
					TOTAL=$((${TOTAL}+${FUDGE}))
					;;
				esac

				for i in ${!COUNT[@]}
				do
					COUNT_STRING="$COUNT_STRING$(printf '[%d]: %d  ' ${i} ${COUNT[${i}]})"
				done

				COUNT_STRING=(${COUNT_STRING})
				COUNT_STRING="${COUNT_STRING[@]}"
				COLOR='#0000ff'
				MESSAGE="$(printf '{"response_type":"%s","text":"*%s%s%s*","attachments":[{"thumb_url":"%s","color":"%s","fields":[{"title":"%s","short":true},{"value":"%s","short":true}],"footer":"%s"}]}' "${RESPONSE}" "${SL_USER}" "${COMMENT}" "${ITER_COMMENT}" "${CHAT_ICON}" "${COLOR}" "${TOTAL}" "${REQUEST//-/−}" "${COUNT_STRING}" )" # Yes, that’s a minus sign substitution; Font Nerd!
				curl -X POST -H 'Content-type: application/json' --url "${response_url}" --silent --fail --data "${MESSAGE}" &> /dev/null
			done
			;;
		*)
			MESSAGE="$(printf '{"response_type":"ephemeral","text":"%sNí thuigim. 分からない。 I do not understand.\n\n%s\n\nI’m afraid what you typed—`%s %s`—made no sense. You can try to explain it to me, but it won’t work. It’s most likely you either mistyped something or you were trying to fool me, and I’m too simple to speculate on the former or fall for the latter."}' "${HELP_HEADER}" "${ROLL_HELP}" "${SLASH}" "${text}")"
			;;
		esac
		;;
	${GM_COMMAND}*)
		case ${GM_AUTH} in
		GM)
			SL_USER="${SUBCOMMAND#${GM_COMMAND}?}"		# Slice off the command and the character after it…
			SPLICER="${SUBCOMMAND:${#GM_COMMAND}:1}"	# … get the character after the command…
			SL_USER="${SL_USER//${SPLICER}/ }"			# … and replace that character with spaces.
			text="${ARGUMENTS[@]}"					# The rest is text.
			ARGUMENTS=( ${text} )

			[ "${SL_USER}" == "${GM_COMMAND}" ] && SL_USER='GM'
			NAME_ARRAY[0]="${SL_USER}"

			case ${ARGUMENTS[0]} in
			${ONLINE_COMMAND})
				unset ARGUMENTS[0]
				matrix "${ARGUMENTS[@]}"
				;;
			${EMOTE})
				unset ARGUMENTS[0]
				meatspace
				;;
			*)
				if [ ${#text} -ne 0 ]
				then
					CHAT_ICON="${DEFAULT_ICON}"
					chatter
				else
					MESSAGE="$(printf '{"response_type":"ephemeral","text":"%sThis GM-only sub-command allows the GM use an arbitrary name in a message.\n\n`%s_Character_Name Message text goes here.`\n\nThe `%s_` will be stripped and all underscores in the remaining `Character_Name` will be converted to a whitespace, e.g. `%s_Character_Name This is a message.` will display like this:","attachments":[{"mrkdwn_in":["text","pretext"],"author_name":"Character Name","text":"This is a message.","author_icon":"%s"},{"mrkdwn_in":["text","pretext"],"pretext":"To display character names with underscores in them, use a character other than an underscore after `%s`, e.g. `%s!The!big_SMALL Your message.` will display like this:","author_name":"The big_SMALL","text":"Your message.","author_icon":"%s"},{"mrkdwn_in":["pretext","text"],"pretext":"If you provide no character name, the text will post with “%s” as the sender, like this: `%s This is a message.`","author_name":"%s","text":"This is a message.","author_icon":"%s"},{"mrkdwn_in":["pretext","text"],"pretext":"Like the non-GM version, `%s` accepts the `%s` for an emote and `%s` for group communication (online, telepathic, etc.), e.g. `%s_Mr._Johnson %s seethes with unbridled hatred.` will display like this:","author_name":"­","text":"_*Mr. Johnson* seethes with unbridled hatred._","author_icon":"%s"}]}' \
						"${HELP_HEADER}" "${SLASH}" \
						"${SUBCOMMAND}" "${SLASH}" "${DEFAULT_ICON}" \
						"${SUBCOMMAND}" "${SLASH}" "${DEFAULT_ICON}" \
						"${SL_USER}" "${SLASH}" "${SL_USER}" "${DEFAULT_ICON}" \
						"${SLASH}" "${EMOTE}" "${ONLINE_COMMAND}" "${SLASH}" "${EMOTE}" "${DEFAULT_ICON}")"
				fi
				;;
			esac
			;;
		*)
			unauthorized
			;;
		esac
		;;
	${EMOTE})
		meatspace
		;;
	*)
		if [ ${#text} -ne 0 ]
		then
			chatter
		else
			case $GM_AUTH in
			'GM')
				GM_MESSAGE="$(printf '\n\nAs an authorized GM, you have access to the `%s %s` command.' \
					"${command}" "${GM_COMMAND}")"
				;;
			esac
			matrix_format "We have trouble inbound!"
			MESSAGE="$(printf '{"response_type":"ephemeral","text":"%s","attachments":[{"mrkdwn_in":["text","pretext"],"pretext":"Properly configured for your game, the default operation is to take a message you type (the text can contain Slack markdown) and display it as in-character talking, e.g. `%s I have a _*bad*_ feeling about this!` will display like this:","author_name":"%s","text":"I have a _*bad*_ feeling about this!","author_icon":"%s"},{"pretext":"If you type `%s %s smirks.`, it formats your message as an emote, for example:","text":"_*%s* smirks._","author_icon":"%s","mrkdwn_in":["text","pretext"]},{"mrkdwn_in":["text","pretext"],"pretext":"The format `%s %s We have trouble inbound!` formats your message as a form of group communication (online, telepathic, etc.), like this:","text":"%s","author_icon":"%s","author_name":"%s"},{"pretext":"In-character direct messages can be sent to any Slack user when sourced from a game channel by putting `%s @username` after `%s`, for example, `%s %s @username %s waves frantically.` Messages will be delivered in-character directly to the user and cloned to the sender. Replying to messages cannot be done via slackbot; it *must* be done from a configured gaming channel. This is awkward, but functional.\n\n`%s %s` invokes a help screen for a dice roller that performs standard NdX±Y gaming dice rolling and other specialized rolls.%s","mrkdwn_in":["text","pretext"]}]}' \
				"${HELP_HEADER}" \
				"${command}" "${SL_USER}" "${CHAT_ICON}" \
				"${command}" "${EMOTE}" "${NAME_ARRAY[0]}" "${DEFAULT_ICON}" \
				"${command}" "${ONLINE_COMMAND}" "${ONLINE_TEXT}" "${ONLINE_ICON}" "${ONLINE_NAME}" \
				"${PRIVMSG_TOKEN}" "${command}" \
				"${command}" "${PRIVMSG_TOKEN}" "${EMOTE}" \
				"${command}" "${ROLL_COMMAND}" "${GM_MESSAGE}")"
		fi
		;;
	esac
	;;
*)
	unauthorized
	;;
esac

[ $((${ITERATIONS})) -eq 0 ] && curl -X POST -H 'Content-type: application/json' --url "${response_url}" --silent --fail --data "${MESSAGE}" &> /dev/null &
[ "${PRIVMSG}" == 'TRUE' ] && curl -X POST --url "${response_url}" --silent --fail --data "${MESSAGE/\"channel\":\"${channel_id}/\"channel\":\"${user_id}}" &> /dev/null &

exit
