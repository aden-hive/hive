# Helper function for choice prompts
prompt_choice() {
    local prompt="$1"
    shift
    local options=("$@")
    local i=1

    # Print menu to stderr so it doesn't get captured by choice="$(...)"
    echo "" >&2
    echo -e "${BOLD}$prompt${NC}" >&2
    for opt in "${options[@]}"; do
        echo -e "  ${CYAN}$i)${NC} $opt" >&2
        ((i++))
    done
    echo "" >&2

    local choice
    while true; do
        read -r -p "Enter choice (1-${#options[@]}): " choice
        if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le "${#options[@]}" ]; then
            # Output ONLY the selected index to stdout
            echo $((choice - 1))
            return 0
        fi
        echo -e "${RED}Invalid choice. Please enter 1-${#options[@]}${NC}" >&2
    done
}

# ... later in the script:

if [ -z "$SELECTED_PROVIDER_ID" ]; then
    echo "No API keys found. Let's configure one."
    echo ""

    choice="$(prompt_choice "Select your LLM provider:" \
        "Anthropic (Claude) - Recommended" \
        "OpenAI (GPT)" \
        "Google Gemini - Free tier available" \
        "Groq - Fast, free tier" \
        "Cerebras - Fast, free tier" \
        "Skip for now")"

    case "$choice" in
        0)
            SELECTED_ENV_VAR="ANTHROPIC_API_KEY"
            SELECTED_PROVIDER_ID="anthropic"
            PROVIDER_NAME="Anthropic"
            SIGNUP_URL="https://console.anthropic.com/settings/keys"
            ;;
        1)
            SELECTED_ENV_VAR="OPENAI_API_KEY"
            SELECTED_PROVIDER_ID="openai"
            PROVIDER_NAME="OpenAI"
            SIGNUP_URL="https://platform.openai.com/api-keys"
            ;;
        2)
            SELECTED_ENV_VAR="GEMINI_API_KEY"
            SELECTED_PROVIDER_ID="gemini"
            PROVIDER_NAME="Google Gemini"
            SIGNUP_URL="https://aistudio.google.com/apikey"
            ;;
        3)
            SELECTED_ENV_VAR="GROQ_API_KEY"
            SELECTED_PROVIDER_ID="groq"
            PROVIDER_NAME="Groq"
            SIGNUP_URL="https://console.groq.com/keys"
            ;;
        4)
            SELECTED_ENV_VAR="CEREBRAS_API_KEY"
            SELECTED_PROVIDER_ID="cerebras"
            PROVIDER_NAME="Cerebras"
            SIGNUP_URL="https://cloud.cerebras.ai/"
            ;;
        5)
            echo ""
            echo -e "${YELLOW}Skipped.${NC} Add your API key later:"
            echo ""
            echo -e "  ${CYAN}echo 'ANTHROPIC_API_KEY=your-key' >> .env${NC}"
            echo ""
            SELECTED_ENV_VAR=""
            SELECTED_PROVIDER_ID=""
            ;;
        *)
            echo -e "${RED}Invalid selection. Please run ./quickstart.sh again.${NC}" >&2
            exit 1
            ;;
    esac

    if [ -n "$SELECTED_ENV_VAR" ] && [ -z "${!SELECTED_ENV_VAR}" ]; then
        echo ""
        echo -e "Get your API key from: ${CYAN}$SIGNUP_URL${NC}"
        echo ""
        read -r -p "Paste your $PROVIDER_NAME API key (or press Enter to skip): " API_KEY

        if [ -n "$API_KEY" ]; then
            # Save to .env
            echo "" >> "$SCRIPT_DIR/.env"
            echo "$SELECTED_ENV_VAR=$API_KEY" >> "$SCRIPT_DIR/.env"
            export "$SELECTED_ENV_VAR=$API_KEY"
            echo ""
            echo -e "${GREEN}⬢${NC} API key saved to .env"
        else
            echo ""
            echo -e "${YELLOW}Skipped.${NC} Add your API key to .env when ready."
            SELECTED_ENV_VAR=""
            SELECTED_PROVIDER_ID=""
        fi
    fi
fi
