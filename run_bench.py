import argparse
import json
import neptune
import dotenv
import logging
import time
from pentest_agent import PentestAgent
from docker_setup import create_container
dotenv.load_dotenv()


print_end_sep = "\n⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"


def log_step(run, step, max_tries, summarized_history, planner_output, cmd_to_run, command_output, summarizer_time, planner_time, challenge, planner_input_token_count, planner_output_token_count, summarizer_input_token_count, summarizer_output_token_count):
	run["challenges"][challenge["name"]]["summarized_history"].log(f"[{step+1}/{max_tries}] {summarized_history}")
	run["challenges"][challenge["name"]]["planner_output"].log(f"[{step+1}/{max_tries}] {planner_output}")
	run["challenges"][challenge["name"]]["commands"].log(f"[{step+1}/{max_tries}] {cmd_to_run}")
	run["challenges"][challenge["name"]]["command_outputs"].log(f"[{step+1}/{max_tries}] {command_output}")

	run["challenges"][challenge["name"]]["planner_time"].log(planner_time)
	run["challenges"][challenge["name"]]["summarizer_time"].log(summarizer_time)

	run["challenges"][challenge["name"]]["planner_input_token_count"].log(planner_input_token_count)
	run["challenges"][challenge["name"]]["planner_output_token_count"].log(planner_output_token_count)
	run["challenges"][challenge["name"]]["summarizer_input_token_count"].log(summarizer_input_token_count)
	run["challenges"][challenge["name"]]["summarizer_output_token_count"].log(summarizer_output_token_count)


def main(challenge, max_tries, pentest_agent):
	if "files" in challenge:
		pentest_agent.download_files(challenge["files"])
		file_names = [url.split("/")[-1] for url in challenge["files"]]
	else:
		file_names = []

	flag = challenge["flag"].strip()

	if "description" not in challenge:
		print("No description was set for this challenge. Setting it to default: There is no information for this level")
		challenge["description"] = "There is no information for this level"

	if "target" in challenge:
		# Overthewire bench
		print(config["target_text"])
		target_text = config["target_text"].format(target=challenge["target"], description=challenge["description"])
	else:
		# Pico Bench
		target_text = f'{config["target_text"]}\nchallenge description: {challenge["description"]}'

	if file_names:
		target_text += f'\nFiles: {",".join(file_names)}'

	pentest_agent.reset()
	pentest_agent.target_text = target_text

	t0 = time.time()
	input_tokens_count = 0
	output_tokens_count = 0
	succeeded = False
	command_errors = 0
	planner_input_token_count_list = []
	summarizer_input_token_count_list = []
	planner_output_token_count_list = []
	summarizer_output_token_count_list = []
	for step in range(max_tries):
		t0_planner = time.time()
		try:
			planner_output, cmd_to_run, command_output, planner_input_token_count, planner_output_token_count = pentest_agent.plan_and_run_cmd(verbose=True)
			if cmd_to_run == "*No command*":
				command_errors += 1
		except Exception as err:
			print(f"Error during plan_and_run_cmd function: {err}")
			command_errors += 1
			continue
		planner_time = time.time() - t0_planner

		t0_summarizer = time.time()
		summarized_history, summarizer_input_token_count, summarizer_output_token_count = pentest_agent.summarizer(verbose=True)
		summarizer_time = time.time() - t0_summarizer

		if flag in summarized_history or flag in command_output:
			succeeded = True
			break

		input_tokens_count += planner_input_token_count
		input_tokens_count += summarizer_input_token_count
		output_tokens_count += planner_output_token_count
		output_tokens_count += summarizer_output_token_count

		planner_input_token_count_list.append(planner_input_token_count)
		summarizer_input_token_count_list.append(summarizer_input_token_count)
		planner_output_token_count_list.append(planner_output_token_count)
		summarizer_output_token_count_list.append(summarizer_output_token_count)

		log_step(
			run=run,
			challenge=challenge,
			step=step,
			planner_output=planner_output,
			cmd_to_run=cmd_to_run,
			command_output=command_output,
			summarized_history=summarized_history,
			max_tries=max_tries,
			planner_time=planner_time,
			summarizer_time=summarizer_time,
			planner_input_token_count=planner_input_token_count,
			planner_output_token_count=planner_output_token_count,
			summarizer_input_token_count=summarizer_input_token_count,
			summarizer_output_token_count=summarizer_output_token_count
		)

	run["challenges"][challenge["name"]]["time"] = time.time() - t0
	run["challenges"][challenge["name"]]["input_tokens_count"] = input_tokens_count
	run["challenges"][challenge["name"]]["output_tokens_count"] = output_tokens_count
	run["challenges"][challenge["name"]]["command_errors"] = command_errors
	run["challenges"][challenge["name"]]["category"] = challenge["category"]
	run["challenges"][challenge["name"]]["planner_input_token_count_list"] = str(planner_input_token_count_list)
	run["challenges"][challenge["name"]]["summarizer_input_token_count_list"] = str(summarizer_input_token_count_list)
	run["challenges"][challenge["name"]]["planner_output_token_count_list"] = str(planner_output_token_count_list)
	run["challenges"][challenge["name"]]["summarizer_output_token_count_list"] = str(summarizer_output_token_count_list)
	if succeeded:
		run["challenges"][challenge["name"]]["finished_in_steps"] = step + 1
	else:
		run["challenges"][challenge["name"]]["finished_in_steps"] = -1
	return succeeded, step


if __name__ == "__main__":

	parser = argparse.ArgumentParser()
	parser.add_argument('-c', '--config', help='Path to config file', required=True)
	parser.add_argument('-b', '--benchmark', help='Path to becnhmark file', required=True)
	parser.add_argument('-k', '--keep-running', action='store_true', help="Don't stop the attackbox after exiting")
	args = parser.parse_args()

	with open(args.config, 'r') as file:
		config = json.load(file)

	container = create_container(config=config)

	with open(args.benchmark, "r") as file:
		benckmark_challenges = json.load(file)
		print(f"Number of challenges loaded: {len(benckmark_challenges)}")

	challenges_to_remove = []
	for challenge, value in benckmark_challenges.items():
		if "flag" not in value:
			print(f"WARNING: Solver function for challenge {challenge} probably has some errors. No flag was found in the challenge.")
			challenges_to_remove.append(challenge)
			continue
		if len(value["flag"].strip()) < 2:
			print(f"WARNING: Solver function for challenge {challenge} probably has some errors. Flag format is wrong.")

			challenges_to_remove.append(challenge)

	for challenge in challenges_to_remove:
		benckmark_challenges.pop(challenge)
		print(f"Removing challenge {challenge}...")

	if challenges_to_remove:
		print(f"Number of challenges kept after removals: {len(benckmark_challenges)}")

	run = neptune.init_run(project=config["neptune"]["project"])
	logging.getLogger("neptune").setLevel(logging.ERROR)
	run["config.json"].upload(args.config)
	run["config"] = neptune.utils.stringify_unsupported(config)

	pentest_agent = PentestAgent(
		llm_model_id=config["llm"]["model_id"],
		llm_model_local=config["llm"]["model_local"],
		container=container,
		planner_system_prompt=config["planner"]["system_prompt"],
		planner_user_prompt=config["planner"]["user_prompt"],
		summarizer_system_prompt=config["summarizer"]["system_prompt"],
		summarizer_user_prompt=config["summarizer"]["user_prompt"],
		temperature=config["llm"]["temperature"],
		top_p=config["llm"]["top_p"],
		timeout_duration=config["timeout_duration"],
		max_new_tokens=config["llm"]["max_new_tokens"],
		new_observation_length_limit=config["new_observation_length_limit"],
		prompt_chaining=config["llm"]["prompt_chaining"],
		do_sample=config["llm"]["do_sample"]
	)

	solved_challenges = 0
	finished_challenges = 0
	for challenge_name in benckmark_challenges:
		# For logging, store the name of the challenge
		challenge = benckmark_challenges[challenge_name]
		challenge["name"] = challenge_name

		success, num_steps = main(
			challenge=challenge,
			max_tries=config["max_tries"],
			pentest_agent=pentest_agent
		)
		finished_challenges += 1
		if success:
			solved_challenges += 1
		print(f"[solved={solved_challenges}|failed={finished_challenges-solved_challenges}|all={len(benckmark_challenges.keys())}] challenge={challenge} success={success} in {num_steps+1}/{config['max_tries']} steps.")
	run["solved_challenges"] = solved_challenges
	run["num_challenges"] = len(benckmark_challenges)
	if not args.keep_running:
		container.stop() # maybe don't delete it, cause it takes a while to re-create
