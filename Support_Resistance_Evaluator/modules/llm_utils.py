import google.generativeai as genai
import toml
from pathlib import Path
from typing import List, Optional


def setup_llm():
    """Setup the LLM model with API key."""
    try:
        # Get the directory where this script is located
        current_dir = Path(__file__).resolve().parent.parent
        api_key_path = current_dir / "api_key" / "gemini_key.toml"

        # Load the API key from the TOML file
        config = toml.load(str(api_key_path))
        api_key = config.get("API_KEY")

        if not api_key or api_key == "your_api_key_here":
            raise ValueError("Please configure your API key in api_key/gemini_key.toml")

        # Configure the generative AI
        genai.configure(api_key=api_key)

        # Get the model - using a lighter version
        model = genai.GenerativeModel("models/gemini-1.5-flash")
        return model

    except Exception as e:
        raise RuntimeError(f"Error setting up LLM: {str(e)}") from e


def get_options_advice(
    model,
    ticker: str,
    current_price: float,
    resistances: List[float],
    supports: List[float],
    context: Optional[str] = None,
    is_follow_up: bool = False,
    follow_up_question: Optional[str] = None,
) -> str:
    """Get options trading advice based on support and resistance levels.

    Args:
        model: The LLM model instance
        ticker: The stock ticker symbol
        current_price: Current stock price
        resistances: List of resistance levels (sorted high to low)
        supports: List of support levels (sorted low to high)

    Returns:
        str: Detailed options trading analysis and recommendations
    """
    # Prepare the prompt
    resistance_str = (
        ", ".join(f"${float(r):.2f}" for r in resistances) if resistances else "None"
    )
    support_str = (
        ", ".join(f"${float(s):.2f}" for s in supports) if supports else "None"
    )

    if is_follow_up and context and follow_up_question:
        prompt = f"""You are an expert options trading advisor. A user is asking a follow-up question about your previous analysis.
        
Previous context:
{context}

User's follow-up question: {follow_up_question}
        
Please provide a focused answer to the user's question in clear Markdown format.
Keep your response concise and specific to the question asked.
Use the same formatting style as the original analysis (with proper price formatting $X.XX).
Remember to reference the current technical levels in your response:
- Current Price: ${float(current_price):.2f}
- Resistance Levels: {resistance_str}
- Support Levels: {support_str}
"""
    else:
        prompt = f"""You are an expert options trading advisor. Analyze the technical levels for {ticker} and provide recommendations in clear Markdown format.
    Use the following data:

    **Current Price:** ${float(current_price):.2f}

    **Resistance Levels** (high to low):
    {resistance_str}

    **Support Levels** (low to high):
    {support_str}

    Provide your analysis in this Markdown format:

    # Options Analysis for {ticker}

    ## 🎯 Option Strategies
    - **Recommended Strategy 1**: [Name]
      - Why: [Clear explanation]
      - Setup: [Specific details]
    - **Recommended Strategy 2**: [if applicable]
      - Why: [Clear explanation]
      - Setup: [Specific details]

    ## 💰 Strike Price Selection
    - **For Calls**: $X.XX (if recommended)
      - Rationale: [Technical explanation]
    - **For Puts**: $X.XX (if recommended)
      - Rationale: [Technical explanation]

    ## ⏳ Expiration Timeframe
    - **Recommended Duration**: X weeks/months
    - **Rationale**: [Clear explanation]

    ## ⚠️ Risk Management
    - **Stop Loss Levels**:
      - Upside: $X.XX
      - Downside: $X.XX
    - **Position Size**: [Recommendation]
    - **Maximum Risk**: [Specific amount or percentage]

    ## 📊 Technical Analysis
    - **Setup Strength**: X/10
    - **Key Levels to Watch**:
      - Strong Resistance: $X.XX
      - Strong Support: $X.XX
    - **Breakout Targets**: $X.XX
    - **Breakdown Risks**: $X.XX

    Remember:
    1. Use only plain numbers (no LaTeX)
    2. Always format prices as $X.XX
    3. Keep explanations clear and concise
    4. Use bullet points for better readability
    5. Highlight important numbers in bold
    """

    try:
        # Validazione dei dati di input
        if not isinstance(resistances, (list, tuple)):
            raise ValueError("resistances must be a list or tuple")
        if not isinstance(supports, (list, tuple)):
            raise ValueError("supports must be a list or tuple")

        # Genera la risposta
        response = model.generate_content(prompt)
        if not response or not hasattr(response, "text"):
            return "Error: No response generated from the model"

        return response.text

    except Exception as e:
        error_msg = str(e)
        if "API key" in error_msg.lower():
            return "Error: Invalid or missing API key. Please check your configuration in api_key/gemini_key.toml"
        else:
            return f"Error getting LLM advice: {error_msg}"
