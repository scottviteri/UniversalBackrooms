import anthropic
import openai
import json
import datetime
import os
import argparse
import dotenv
import sys
import colorsys
import requests

# Attempt to load from .env file, but don't override existing env vars
dotenv.load_dotenv(override=False)

MODEL_INFO = {
    "sonnet": {
        "api_name": "claude-3-5-sonnet-20240620",
        "display_name": "Claude",
        "company": "anthropic",
    },
    "opus": {
        "api_name": "claude-3-opus-20240229",
        "display_name": "Claude",
        "company": "anthropic",
    },
    "gpt4o": {
        "api_name": "gpt-4o-2024-08-06",
        "display_name": "GPT4o",
        "company": "openai",
    },
    "o1-preview": {"api_name": "o1-preview", "display_name": "O1", "company": "openai"},
    "o1-mini": {"api_name": "o1-mini", "display_name": "Mini", "company": "openai"},
}


def claude_conversation(actor, model, context, system_prompt=None):
    messages = [{"role": m["role"], "content": m["content"]} for m in context]

    # If Claude is the first model in the conversation, it must have a user message
    kwargs = {
        "model": model,
        "max_tokens": 1024,
        "temperature": 1.0,
        "messages": messages,
    }
    if system_prompt:
        kwargs["system"] = system_prompt
    message = anthropic_client.messages.create(**kwargs)
    return message.content[0].text


def gpt4_conversation(actor, model, context, system_prompt=None):
    messages = [{"role": m["role"], "content": m["content"]} for m in context]

    kwargs = {
        "model": model,
        "messages": messages,
        "temperature": 1.0,
    }

    if model == "o1-preview" or model == "o1-mini":
        kwargs["max_tokens"] = 4000
    else:
        kwargs["max_tokens"] = 1024

    response = openai_client.chat.completions.create(**kwargs)
    return response.choices[0].message.content


def load_template(template_name, models):
    try:
        with open(f"templates/{template_name}.jsonl", "r") as f:
            configs = [json.loads(line) for line in f]

        companies = []
        actors = []
        for i, model in enumerate(models):
            if model.lower() == "cli":
                companies.append("CLI")
                actors.append("CLI")
            else:
                companies.append(MODEL_INFO[model]["company"])
                actors.append(f"{MODEL_INFO[model]['display_name']} {i+1}")

        for i, config in enumerate(configs):
            if models[i].lower() == "cli":
                config["cli"] = True
                continue

            config["system_prompt"] = config["system_prompt"].format(
                **{f"lm{j+1}_company": companies[j] for j in range(len(companies))},
                **{f"lm{j+1}_actor": actors[j] for j in range(len(actors))},
            )
            for message in config["context"]:
                message["content"] = message["content"].format(
                    **{f"lm{j+1}_company": companies[j] for j in range(len(companies))},
                    **{f"lm{j+1}_actor": actors[j] for j in range(len(actors))},
                )

            if (
                models[i] in MODEL_INFO
                and MODEL_INFO[models[i]]["company"] == "openai"
                and config["system_prompt"]
            ):
                system_prompt_added = False
                for message in config["context"]:
                    if message["role"] == "user":
                        message["content"] = (
                            f"<SYSTEM>{config['system_prompt']}</SYSTEM>\n\n{message['content']}"
                        )
                        system_prompt_added = True
                        break
                if not system_prompt_added:
                    config["context"].append(
                        {
                            "role": "user",
                            "content": f"<SYSTEM>{config['system_prompt']}</SYSTEM>",
                        }
                    )
            config["cli"] = config.get("cli", False)
        return configs
    except FileNotFoundError:
        print(f"Error: Template '{template_name}' not found.")
        exit(1)
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON in template '{template_name}'.")
        exit(1)


def get_available_templates():
    template_dir = "./templates"
    templates = []
    for file in os.listdir(template_dir):
        if file.endswith(".jsonl"):
            templates.append(os.path.splitext(file)[0])
    return templates


def main():
    global anthropic_client
    global openai_client
    parser = argparse.ArgumentParser(
        description="Run conversation between two or more AI language models."
    )
    parser.add_argument(
        "--lm",
        choices=["sonnet", "opus", "gpt4o", "o1-preview", "o1-mini", "cli"],
        nargs="+",
        default=["opus", "opus"],
        help="Choose the models for LMs or 'cli' for the world interface (default: opus opus)",
    )

    available_templates = get_available_templates()
    parser.add_argument(
        "--template",
        choices=available_templates,
        default="cli" if "cli" in available_templates else available_templates[0],
        help=f"Choose a conversation template (available: {', '.join(available_templates)})",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=float("inf"),
        help="Maximum number of turns in the conversation (default: infinity)",
    )
    args = parser.parse_args()

    # Only create new database if CLI is one of the models
    if 'cli' in [m.lower() for m in args.lm]:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        db_path = os.path.join(os.path.dirname(__file__), '..', 'world-interface', 'data', f'notes-{timestamp}.db')
        
        # Ensure data directory exists
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        
        # Initialize database through world-interface
        headers = {
            "Authorization": f"Bearer {os.getenv('WORLD_INTERFACE_KEY')}",
            "Content-Type": "application/json",
        }
        response = requests.post(
            "http://localhost:3000/v1/db/init",
            json={"dbPath": db_path},
            headers=headers,
        )
        response.raise_for_status()

    models = args.lm
    lm_models = []
    lm_display_names = []

    companies = []
    actors = []

    for i, model in enumerate(models):
        if model.lower() == "cli":
            lm_display_names.append("CLI")
            lm_models.append("cli")
            companies.append("CLI")
            actors.append("CLI")
        else:
            if model in MODEL_INFO:
                lm_display_names.append(f"{MODEL_INFO[model]['display_name']} {i+1}")
                lm_models.append(MODEL_INFO[model]["api_name"])
                companies.append(MODEL_INFO[model]["company"])
                actors.append(f"{MODEL_INFO[model]['display_name']} {i+1}")
            else:
                print(f"Error: Model '{model}' not found in MODEL_INFO.")
                sys.exit(1)

    # Filter out models not in MODEL_INFO (like 'cli')
    anthropic_models = [
        model
        for model in models
        if model in MODEL_INFO and MODEL_INFO[model]["company"] == "anthropic"
    ]
    if anthropic_models:
        anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
        if not anthropic_api_key:
            print(
                "Error: ANTHROPIC_API_KEY must be set in the environment or in a .env file."
            )
            sys.exit(1)
        anthropic_client = anthropic.Client(api_key=anthropic_api_key)

    openai_models = [
        model
        for model in models
        if model in MODEL_INFO and MODEL_INFO[model]["company"] == "openai"
    ]
    if openai_models:
        openai_api_key = os.getenv("OPENAI_API_KEY")
        if not openai_api_key:
            print(
                "Error: OPENAI_API_KEY must be set in the environment or in a .env file."
            )
            sys.exit(1)
        openai_client = openai.OpenAI(api_key=openai_api_key)

    configs = load_template(args.template, models)

    assert len(models) == len(
        configs
    ), f"Number of LMs ({len(models)}) does not match the number of elements in the template ({len(configs)})"

    system_prompts = [config.get("system_prompt", "") for config in configs]
    contexts = [config.get("context", []) for config in configs]

    logs_folder = "BackroomsLogs"
    if not os.path.exists(logs_folder):
        os.makedirs(logs_folder)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{logs_folder}/{'_'.join(models)}_{args.template}_{timestamp}.txt"

    turn = 0
    while turn < args.max_turns:
        for i in range(len(models)):
            if models[i].lower() == "cli":
                lm_response = cli_conversation(contexts[i])
            else:
                lm_response = generate_model_response(
                    lm_models[i],
                    lm_display_names[i],
                    contexts[i],
                    system_prompts[i],
                )
            process_and_log_response(
                lm_response,
                lm_display_names[i],
                filename,
                contexts,
                i,
            )
        turn += 1

    print(f"\nReached maximum number of turns ({args.max_turns}). Conversation ended.")
    with open(filename, "a") as f:
        f.write(
            f"\nReached maximum number of turns ({args.max_turns}). Conversation ended.\n"
        )


def generate_model_response(model, actor, context, system_prompt):
    if model.startswith("claude-"):
        return claude_conversation(
            actor, model, context, system_prompt if system_prompt else None
        )
    else:
        return gpt4_conversation(
            actor, model, context, system_prompt if system_prompt else None
        )


def generate_distinct_colors():
    hue = 0
    golden_ratio_conjugate = 0.618033988749895
    while True:
        hue += golden_ratio_conjugate
        hue %= 1
        rgb = colorsys.hsv_to_rgb(hue, 0.95, 0.95)
        yield tuple(int(x * 255) for x in rgb)


color_generator = generate_distinct_colors()
actor_colors = {}


def get_ansi_color(rgb):
    return f"\033[38;2;{rgb[0]};{rgb[1]};{rgb[2]}m"


def process_and_log_response(response, actor, filename, contexts, current_model_index):
    global actor_colors

    # Get or generate a color for this actor
    if actor not in actor_colors:
        actor_colors[actor] = get_ansi_color(next(color_generator))

    color = actor_colors[actor]
    bold = "\033[1m"
    reset = "\033[0m"

    # Create a visually distinct header for each actor
    console_header = f"\n{bold}{color}{actor}:{reset}"
    file_header = f"\n### {actor} ###\n"

    print(console_header)
    print(response)

    with open(filename, "a") as f:
        f.write(file_header)
        f.write(response + "\n")

    if "^C^C" in response:
        end_message = f"\n{actor} has ended the conversation with ^C^C."
        print(end_message)
        with open(filename, "a") as f:
            f.write(end_message + "\n")
        exit()

    # Add the response to all contexts
    for i, context in enumerate(contexts):
        role = "assistant" if i == current_model_index else "user"
        context.append({"role": role, "content": response})


def cli_conversation(context):
    # Extract the last user message
    last_message = context[-1]["content"]
    # Prepare the payload
    payload = {"messages": [{"role": "user", "content": last_message}]}
    headers = {
        "Authorization": f"Bearer {os.getenv('WORLD_INTERFACE_KEY')}",
        "Content-Type": "application/json",
    }
    # Send POST request to the world-interface
    response = requests.post(
        "http://localhost:3000/v1/chat/completions",
        json=payload,
        headers=headers,
    )
    response.raise_for_status()
    response_data = response.json()
    cli_response = response_data["choices"][0]["message"]["content"]
    return cli_response


if __name__ == "__main__":
    main()
