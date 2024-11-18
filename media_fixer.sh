#!/bin/bash
# By Willy Gardiol, provided under the GPLv3 License. https://www.gnu.org/licenses/gpl-3.0.html
# Publicly available at: https://github.com/gardiol/media_fixer
# You can contact me at willy@gardiol.org


# where is your "mediainfo" executable
MEDIAINFO_EXE=$(which mediainfo)
# where is your "ffmpeg" executable
FFMPEG_EXE=$(which ffmpeg)
CP_EXE=$(which cp)
MV_EXE=$(which mv)
RM_EXE=$(which rm)


# Define how your videos needs to be converted to.
#
# Which container format to use
CONTAINER="Matroska"
CONTAINER_EXTENSION="mkv"
# Which codec to use for re-encoding if needed
VIDEO_CODEC="AV1"
# Which video resolution to aim for
VIDEO_WIDTH="1280"
VIDEO_HEIGHT="720"

# Additional FFMPEG specific settings
FFMPEG_EXTRA_OPTS="-fflags +genpts"
FFMPEG_ENCODE="-c:v libsvtav1 -crf 38"
FFMPEG_RESIZE="-vf scale=${VIDEO_WIDTH}:${VIDEO_HEIGHT}"

# loggig, debugging and general print functions
function print_debug
{
	test ${DEBUG} -eq 1 && echo ' [DEBUG] '$@  | tee -a "${LOG_FILE}"
}

function print_log
{
	echo $@ > "${LOG_FILE}"
}

function print_notice
{
	echo $@ | tee -a "${LOG_FILE}"
}

function print_error
{
	echo ' [ERROR] '$@ | tee -a "${LOG_FILE}"
}

function trim() {
    local var="$*"
    # remove leading whitespace characters
    var="${var#"${var%%[![:space:]]*}"}"
    # remove trailing whitespace characters
    var="${var%"${var##*[![:space:]]}"}"
    printf '%s' "$var"
}

function exec_command
{
        print_log "- running command: '""$@""'"
        if [ ${TEST_ONLY} -eq 1 ]
        then
                print_notice " (command not executed because TEST_ONLY=1) "
        else
                "$@" &>> "${LOG_FILE}"
        fi
}


function parse_mediainfo_output
{
	local filename=$1
	local section=$2
	local row=$3

	local value=
	local section_found=0
	local row_found=0
	export mediainfo_value=$("${MEDIAINFO_EXE}" "$filename" | while read line
	do
		if [ $section_found -eq 0 ]
		then
			test "$line" = "$section" && section_found=1
		else
			if [ -z "$line" ]
			then
				return 255
			else
				local left=
				local right=
				IFS=: read left right <<< "$line"
				if [ "$(trim "$left")" = "$row" ]
				then
					echo $(trim "$right")
					return 0
				fi
			fi
		fi
	done)
	
	if [ $? -eq 0 ]
	then
		return 0
	else
		echo "ERROR: '$row' in '$section' not found"
		return 255
	fi
}

function preprocess_video_file()
{
	local full_filename="$*"

	local l_result=2 # 0= failed, 1= success, 2= skipped
	local l_change_container=0
	local l_encode=0
	local l_resize=0

	print_notice "Analyzing file '${full_filename}'..."

	parse_mediainfo_output "${full_filename}" "General" "Format"
	if [ $? -eq 0 ]
	then
		if [ "${mediainfo_value}" != "${CONTAINER}" ]
		then
			print_notice "Container needs to be converted from '${mediainfo_value}' to '${CONTAINER}'..."
			l_change_container=1
		else 
			print_notice "Container already '${CONTAINER}'."
		fi

		parse_mediainfo_output "${full_filename}" "Video" "Format"
		if [ $? -eq 0 ]
		then
			if [ "${mediainfo_value}" != "${VIDEO_CODEC}" ]
			then
				print_notice "Movie needs to be encoded from '${mediainfo_value}' to '${VIDEO_CODEC}'..."
				l_encode=1
			else 
				print_notice "Video already at '${VIDEO_CODEC}' encoding."
			fi
			parse_mediainfo_output "${full_filename}" "Video" "Height"
			mediainfo_value="${mediainfo_value% *}"
			if [ $? -eq 0 ]
			then
				# remove blanks inside height string (since mediainfo will report 1080 as "1 080"):
				mediainfo_value=${mediainfo_value//[[:space:]]/}
				if [ "${mediainfo_value}" != "${VIDEO_HEIGHT}" ]
				then
					if [ ${mediainfo_value} -gt ${VIDEO_HEIGHT} ]
					then
						print_notice "Movie needs to be resized from '${mediainfo_value}' to '${VIDEO_HEIGHT}'..."
						l_resize=1
					else
						print_notice "Not resizing upward: '${mediainfo_value}' is smaller than '${VIDEO_HEIGHT}'."
					fi
				else 
					print_notice "Video already at '${VIDEO_HEIGHT}' resolution."
				fi
			else
				print_error "Unable to parse Video Height"
				l_result=0
			fi
		else
			print_error "Unable to parse Video Format"
			l_result=0
		fi
	else
		print_error "Unable to parse General Format"
		l_result=0
	fi

	if [ $l_result -eq 0 ]
	then
		print_notice "   Video is invalid or corrupted and cannot be processed."
	else
		if [ $l_change_container -eq 1 -o $l_encode -eq 1 -o $l_resize -eq 1 ]
		then
			l_result=1
			print_notice "   Video needs to be processed."
		fi
	fi
	export result=$l_result
	export change_container=$l_change_container
	export encode=$l_encode
	export resize=$l_resize
}

function print_usage()
{
	echo "Media Fixer - Reconvert your videos to your preferred container, codec and sizing"
	echo "Usage:"
	echo "   $0 [-l logfile] [-a] [-p path] [-q path] [-r prefix] [-t] [-d]"
	echo "  -l logfile - use logfile as logfile (optional)"
	echo "  -q path    - folder where the queue files will be stored (optional)"
	echo "  -r prefix  - prefix to use for personalized queue filenames (optional)"
	echo "  -a         - start from current folder to scan for videos"
	echo "  -p path    - start from path to scan for videos"
	echo "  -t         - force test mode on - default off (optional)"
	echo "  -d         - force debug mode on - default off  (optional)"
	echo " Either '-a' or '-p' must be present."
	echo " If '-l' is omitted, the logfile will be in current folder and called 'media_fixed.log'"
}

######### Begin of script #############

#### Ensure needed executables do exist
if [ "${MEDIAINFO_EXE}" = "" -o ! -e ${MEDIAINFO_EXE} ]
then
	echo "ERROR: missing 'mediainfo' executable, please install the mediainfo package."
	exit 255
fi

if [ "${FFMPEG_EXE}" = "" -o ! -e ${FFMPEG_EXE} ]
then
	echo "ERROR: missing 'ffmpeg' executable, please install the ffmpeg package."
	exit 255
fi

SCAN_PATH="$(pwd)"
QUEUE_PATH="${SCAN_PATH}"
LOG_FILE="${SCAN_PATH}/media_fixer.log"
PREFIX=""
TEST_ONLY=0
DEBUG=0
if [ "$1" = "" ]
then
	print_usage
	exit 2
else
	#### Parse commnand line
	while getopts "hal:p:q:r:td" OPTION
	do
	        case $OPTION in
	        l)
			LOG_FILE="${OPTARG}"
	                ;;
		p)
			SCAN_PATH="${OPTARG}"
			;;
		a)
			;;
		q)
			QUEUE_PATH="${OPTARG}"
			;;
		r)
			PREFIX="${OPTARG}"
			;;
		d)
			DEBUG=1
			;;
		t)
			TEST_ONLY=1
			;;
	        h|*)
			print_usage
	                exit 1
	                ;;
	        esac
	done
fi

if [ ! -d ${SCAN_PATH} ]
then
	echo "ERROR: scan path '${SCAN_PATH}' does not exist!"
	exit 254
fi

if [ ! -d ${QUEUE_PATH} ]
then
	echo "ERROR: custom queue path '${QUEUE_PATH}' does not exist!"
	exit 254
fi

# Check valid log file
test -z "${LOG_FILE}" && LOG_FILE=/dev/null
test ${TEST_ONLY} -eq 1 && DEBUG=1

# From now on, we can use the print_notice / print_debug etc functions...

print_notice "Running Media Fixer on $(date)"
print_notice "   Logfile: '${LOG_FILE}'"
test ${TEST_ONLY} -eq 1 && print_notice "Running in TEST mode"
test ${DEBUG} -eq 1 && print_notice "Running in DEBUG mode"
print_notice "   Base path: '${SCAN_PATH}'"
print_notice "   Queue path: '${QUEUE_PATH}'"

# Move to SCAN_PATH...

(cd ${SCAN_PATH} && {
# A few "queue files" are created:
# ${queue_file}.temp         = store list of videos before they are analyzed
#  ${queue_file}.skipped     = store videos that does not need to be converted
#  ${queue_file}.failed      = store videos which failed to parse or convert
#  ${queue_file}.completed   = store list of videos successfully converted
#  ${queue_file}.in_progress = store list of video that needs (yet) to be converted
#
#  If the in_progress is present, and in_progress is not empty, videos will NOT be analyzed and searched again.
#  This is useful to stop execution and restart later.
#  If the in_progress file is missing or empty, the video search and analysis step is performed.
#
create_queue=0
queue_file="${QUEUE_PATH}/${PREFIX}processing_queue"
if [ -e ${queue_file}.in_progress ]
then
	line=$(head -n 1 ${queue_file}.in_progress)
	if [ "${line}" = "" ]
	then
		create_queue=1
	fi
else
	create_queue=1
fi

# Perform video files search
if [ ${create_queue} -eq 1 ]
then
	# Scan folders / subfolders to find video files...
	print_notice "Calculating queues..."
	for j in skipped failed completed in_progress temp
	do
		test -e ${queue_file}.${j} && "${RM_EXE}" ${queue_file}.${j}
	done

	find . -type f -exec file -N -i -- {} + | sed -n 's!: video/[^:]*$!!p' | {
	while read line
	do
		# temp files end with ".working", those needs to be ignored
		is_temp=${line%working}
		if [ "${line%working}" = "${line}" ]
		then
			echo ${line} >> ${queue_file}.temp
		else
			print_notice "Skipping file '${line}' because it seems a temporary file, you should maybe delete it?"
		fi
	done
	}

	# Prevent error if no video files have been found
	test -e ${queue_file}.temp || touch ${queue_file}.temp

	print_notice "Queue has "$(cat ${queue_file}.temp | wc -l)" videos to be analyzed..."

	# Iterate all files in the temporary queue...
	line=$(head -n 1 ${queue_file}.temp)
	while [ "${line}" != "" ]
	do
		result=0
		change_container=0
		encode=0
		resize=0
		preprocess_video_file "${line}"
	
		# Remove file from queue...
		tail -n +2 ${queue_file}.temp > ${queue_file}.cleaned
		"${MV_EXE}" ${queue_file}.cleaned ${queue_file}.temp
	
		# Move file to appropriate new queue
		if [ $result -eq 0 ]
		then
			# add file to failed queue
			print_notice "Video '${line}' added to failed queue"
			echo ${line} >> ${queue_file}.failed
		elif [ $result -eq 2 ]
		then
			# add file to skipped queue
			print_notice "Video '${line}' added to skipped queue"
			echo ${line} >> ${queue_file}.skipped
		elif [ $result -eq 1 ]
		then
			# add file to process queue
			print_notice "Video '${line}' added to processing queue (${change_container} ${encode} ${resize})"
		echo "${line}|||| ${change_container} ${encode} ${resize}" >> ${queue_file}.in_progress
		else
			print_notice "Invalid value of '$result' in result!"
		fi
		line=$(head -n 1 ${queue_file}.temp)
	done
fi # rescan all video files


# Prevent errors in the following if the various queue files have not been created
test -e ${queue_file}.failed || touch ${queue_file}.failed
test -e ${queue_file}.skipped || touch ${queue_file}.skipped
test -e ${queue_file}.in_progress || touch ${queue_file}.in_progress

print_notice "Failed queue has "$(cat ${queue_file}.failed | wc -l)" videos."
print_notice "Skipped queue has "$(cat ${queue_file}.skipped | wc -l)" videos."
print_notice "Work queue has "$(cat ${queue_file}.in_progress | wc -l)" videos to be processed..."


# Iterate the in_progress queue...
line=$(head -n 1 ${queue_file}.in_progress)
while [ "${line}" != "" ]
do
	result=0

	full_filename=${line%||||*}
	filepath="${full_filename%/*}"
	filename="${full_filename##*/}"
	extension="${filename##*.}"
	stripped_filename="${filename%.*}"
	
	temp=${line#*||||}
	change_container=${temp%[[:space:]][[:digit:]][[:space:]][[:digit:]]}
	encode=${temp%[[:space:]][[:digit:]]}
	encode=${encode#[[:space:]][[:digit:]][[:space:]]}
	resize=${temp##[[:space:]][[:digit:]][[:space:]][[:digit:]][[:space:]]}

	echo "Processing: '$full_filename'..."

	if [ $change_container -eq 1 -o $encode -eq 1 -o $resize -eq 1 ]
	then
		result=0
		print_notice "   Video needs to be processed."
		my_cwd="$PWD"
		print_notice "Relocating to path '${filepath}' for easier operations..."
		if cd "${filepath}"
		then
			error=0
			working_filename="${stripped_filename}.working"			
			print_notice "Copying original to '${working_filename}'..."
			exec_command "${CP_EXE}" "${filename}" "${working_filename}" &>> "${LOG_FILE}"

			if [ $change_container -eq 1 ]
			then 
				intermediate_filename="${stripped_filename}.tmuxed".${CONTAINER_EXTENSION}
				print_notice "Transmuxing from '${working_filename}' to '${intermediate_filename}'..."
				exec_command "${FFMPEG_EXE}" -fflags +genpts -nostdin -find_stream_info -i "${working_filename}" -map 0 -map -0:d -codec copy -codec:s srt "${intermediate_filename}" &>> "${LOG_FILE}"
				if [ $? -eq 0 ]
				then
					print_notice "Transmux ok."
					exec_command "${MV_EXE}" "${intermediate_filename}" "${working_filename}" &>> "${LOG_FILE}"
				else
					print_error "Transmux failed!"
					exec_command "${RM_EXE}" -f "${intermediate_filename}"
					error=1
				fi
			fi # transmux

			if [ $error -eq 0 ]
			then
				if [ $encode -eq 1 -o $resize -eq 1 ]
				then
					source_filename="${working_filename}"
					intermediate_filename="${stripped_filename}.encoded".${CONTAINER_EXTENSION}
					print_notice "Encoding from '${source_filename}' to '${intermediate_filename}'" 

					ffmpeg_options=
					if [ $encode -eq 1 ]
					then
						ffmpeg_options=${FFMPEG_ENCODE}
					fi
	
					if [ $resize -eq 1 ]
					then
						ffmpeg_options="${ffmpeg_options} ${FFMPEG_RESIZE}"
					fi

					exec_command "${FFMPEG_EXE}" -fflags +genpts -nostdin -i "${source_filename}" ${ffmpeg_options} "${intermediate_filename}"
					if [ $? -eq 0 ]
					then
						print_notice "Encoding ok."
						exec_command "${MV_EXE}" "${intermediate_filename}" "${working_filename}"
					else
						print_error "Encoding failed!"
						exec_command "${RM_EXE}" -f "${intermediate_filename}"
						error=1
					fi
				fi # encore or resize
			fi # error = 0

			if [ $error -eq 0 ]
			then
				if [ -e "${working_filename}" ]
				then
					destination_filename="${stripped_filename}.${CONTAINER_EXTENSION}"
					print_notice "Moving final product from '${working_filename}' to '${destination_filename}'..."
					exec_command "${MV_EXE}" "${working_filename}" "${destination_filename}"
					if [ $? -eq 0 ]
					then
						result=1
						if [ "${filename}" != "${destination_filename}" ]
						then
							print_notice "Removing original file..."
							exec_command "${RM_EXE}" -f "${filename}"
						else
							print_notice "Original file has been replaced with converted file."
						fi
					else
						print_error "Unable to move converted file, not deleting original."
					fi
				else
					print_error "Missing working file '${working_filename}', something went wrong!"
				fi
			else
				print_error "Something went wrong in conversion."
			fi
			cd "$my_cwd"
		else
			print_error "Unable to cd to '${filepath}'"
		fi 
		
	fi # change container or encode

	print_notice "Removing processed file from processing queue..."
	if [ ${result} -eq 1 ]
	then
		echo ${line} >> ${queue_file}.completed
	else
		echo ${full_filename} >> ${queue_file}.failed
	fi

	# remove from queue
	tail -n +2 ${queue_file}.in_progress > ${queue_file}.cleaned
	"${MV_EXE}" ${queue_file}.cleaned ${queue_file}.in_progress
	line=$(head -n 1 ${queue_file}.in_progress)

done

}) # moved to SCAN_PATH

print_notice "All done."
exit 0

