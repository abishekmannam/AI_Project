import os
import time
import json
import random
import asyncio
import streamlit as st
from typing import Literal, Optional, List, Dict
from google.genai import types
from pydantic import BaseModel, Field
from google.adk.runners import Runner
from google.adk.tools import google_search, agent_tool
from google.adk.agents import Agent, LlmAgent, SequentialAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.sessions import InMemorySessionService

st.set_page_config(
    page_title="Hotel Reservation Agent",
    page_icon="🏨",
    layout="wide",
    initial_sidebar_state="expanded"
)

APP_NAME="hotels_app"
USER_ID="user_1"
SESSION_ID="session_001"
SESSION_SERVICE= InMemorySessionService()

async def create_session():
    await SESSION_SERVICE.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        session_id=SESSION_ID
    )
asyncio.run(create_session())

# CORRECTED instructions for a proper JSON list output
HOTEL_SEARCH_AGENT_INSTRUCTIONS = """
You are a hotel search assistant. Your goal is to find hotel names and basic information based on the user's query.

Return JSON only. Do not return prose, markdown, bullet lists, or explanations outside the JSON object.

**Your Workflow:**
1. Use Google Search to find hotels based on the user's location query.
2. Extract the hotel name, its general location (e.g., the city), a rating, and an estimated cost.
3. STRICTLY follow this JSON output format. The 'hotels' key must contain a non-empty list of hotel objects:
    {
        "text": "Brief one sentence summary of the search results.",
        "hotels": [
            {
                "hotel_name": "Name of Hotel",
                "location": "City or Area, Country",
                "rating": 4.5,
                "cost": 150
            }
        ]
    }
4. Return 5 to 15 hotels whenever possible. If exact budget matches are limited, return the closest available options and keep the list non-empty.
  
**Search Guidelines:**
- Use multiple search queries if needed to get comprehensive results.
- Extract hotel names, rating, cost estimates in USD, and the location.
- For budget searches, prioritize hotels that appear likely to match the user's budget, but do not omit the hotel list.
"""

# NEW BOOKING AGENT INSTRUCTIONS
BOOKING_AGENT_INSTRUCTIONS = """
You are a hotel booking assistant. Your role is to help users complete hotel bookings in a conversational manner.

**Your Workflow:**
1. When a user says they want to book a hotel (e.g., "book JW Hotel", "proceed to booking"), acknowledge their request and ask them to select a room type.
2. Present available room types with features (no prices shown).
3. After they select a room type, collect necessary booking details (check-in/check-out dates, number of guests).
4. Confirm the booking details and process the booking.
5. Provide a booking confirmation message.

**Room Types to Offer:**
- Standard Room - Basic amenities, city view
- Deluxe Room - Premium amenities, partial city view
- Executive Suite - Spacious suite, city view, executive lounge access
- Presidential Suite - Luxury suite, panoramic view, butler service

**Booking Flow:**
1. Confirm hotel selection
2. Ask for room type selection
3. Ask for check-in and check-out dates
4. Ask for number of guests
5. Confirm all details
6. Process booking and provide confirmation

**Response Format:**
Always respond in a friendly, conversational manner. Use emojis and formatting to make the interaction engaging.
"""


if not os.getenv("GOOGLE_API_KEY"):
    raise RuntimeError(
        "Missing GOOGLE_API_KEY. Set it in your shell before running the app."
    )

class HotelSearchOutput(BaseModel):
    class Hotel(BaseModel):
        hotel_name: str
        location: str
        price: float = 0
        rating: float = Field(default=0, ge=0, le=5)
        link: str = ""

    output: list[Hotel]

HOTEL_SEARCH_AGENT = LlmAgent(
    name="hotel_search_agent",
    model="gemini-2.5-flash",
    description="Hotel Search Agent",
    instruction=HOTEL_SEARCH_AGENT_INSTRUCTIONS,
    generate_content_config=types.GenerateContentConfig(temperature=0),
    tools=[google_search]
)

BOOKING_AGENT = LlmAgent(
    name="booking_agent",
    model="gemini-2.5-flash",
    description="Hotel Booking Agent",
    instruction=BOOKING_AGENT_INSTRUCTIONS,
    generate_content_config=types.GenerateContentConfig(temperature=0.3),
    tools=[]
)

# Store booking state
if "booking_state" not in st.session_state:
    st.session_state.booking_state = {
        "active": False,
        "hotel_name": "",
        "room_type": "",
        "check_in": "",
        "check_out": "",
        "guests": 0,
        "total_price": 0,
        "step": "initial"  # initial, room_selection, date_selection, guest_selection, confirmation
    }

SEARCH_RUNNER = Runner(agent=HOTEL_SEARCH_AGENT, app_name=APP_NAME, session_service=SESSION_SERVICE)
BOOKING_RUNNER = Runner(agent=BOOKING_AGENT, app_name=APP_NAME, session_service=SESSION_SERVICE)

def mock_api_get_hotel_prices(hotel_name: str, location: str) -> Dict[str, Dict]:
    booking_sites = [
        "Booking.com", "Agoda", "MakeMyTrip", "Trivago",
        "Hotels.com", "Expedia", "Goibibo", "Cleartrip"
    ]
    hotel_prices = {}
    for site in booking_sites:
        if random.random() <= 0.8:
            price = random.randint(80, 450)
            site_domain = site.lower().replace(" ", "").replace(".", "")
            mock_link = f"https://www.{site_domain}.com/hotel/{hotel_name.lower().replace(' ', '-')}"
            hotel_prices[site] = {"price": price, "available": True, "link": mock_link, "currency": "USD"}
        else:
            hotel_prices[site] = {"price": None, "available": False, "link": None, "currency": "USD"}
    return hotel_prices

def get_best_hotel_deals(hotels_list: List[Dict]) -> List[Dict]:
    """
    Get prices for all hotels from multiple sites and return sorted by lowest price.
    """
    enhanced_hotels = []
    for hotel in hotels_list:
        hotel_name = hotel.get('hotel_name', '')
        location = hotel.get('location', '')
        site_prices = mock_api_get_hotel_prices(hotel_name, location)
        
        available_prices = [
            {'site': site, 'price': details['price'], 'link': details['link']}
            for site, details in site_prices.items()
            if details['available'] and details.get('price') is not None
        ]
        
        # This block contains the fix
        if available_prices:
            best_deal = min(available_prices, key=lambda x: x['price'])
            
            # Safely get the rating, defaulting to 0 if it's None or missing
            rating_from_agent = hotel.get('rating')
            safe_rating = rating_from_agent if rating_from_agent is not None else 0
            
            enhanced_hotel = {
                'hotel_name': hotel_name,
                'location': location,
                'price': best_deal['price'],
                'rating': safe_rating,  # Use the safe, non-None value
                'link': best_deal['link'],
                'price_source': best_deal['site'],
                'all_prices': site_prices
            }
        else:
            # Also ensure rating is safe here for hotels with no available prices
            rating_from_agent = hotel.get('rating')
            safe_rating = rating_from_agent if rating_from_agent is not None else 0
            enhanced_hotel = {
                'hotel_name': hotel_name, 'location': location, 'price': 0,
                'rating': safe_rating, 'link': '',
                'price_source': 'Not Available', 'all_prices': site_prices
            }
        enhanced_hotels.append(enhanced_hotel)
    
    enhanced_hotels.sort(key=lambda x: (x['price'] == 0, x['price']))
    return enhanced_hotels

def detect_booking_intent(prompt: str) -> bool:
    """Detect if user wants to book a hotel"""
    booking_keywords = [
        "book", "booking", "reserve", "reservation", "proceed to booking",
        "i want to book", "book hotel", "make a booking", "reserve hotel"
    ]
    return any(keyword in prompt.lower() for keyword in booking_keywords)

def extract_hotel_name_from_booking_request(prompt: str) -> str:
    """Extract hotel name from booking request"""
    prompt_lower = prompt.lower()
    
    # Look for patterns like "book [hotel name]" or "book the [hotel name]"
    if "book" in prompt_lower:
        parts = prompt_lower.split("book")
        if len(parts) > 1:
            hotel_part = parts[1].strip()
            # Remove common words
            hotel_part = hotel_part.replace("the ", "").replace("hotel", "").strip()
            return hotel_part.title()
    
    return ""

def get_room_types():
    """Get available room types without prices"""
    return [
        {"type": "Standard Room", "description": "Basic amenities, city view"},
        {"type": "Deluxe Room", "description": "Premium amenities, partial city view"},
        {"type": "Executive Suite", "description": "Spacious suite, city view, executive lounge access"},
        {"type": "Presidential Suite", "description": "Luxury suite, panoramic view, butler service"}
    ]

def process_booking_step(prompt: str, current_step: str):
    """Process different steps of booking flow"""
    if current_step == "initial":
        hotel_name = extract_hotel_name_from_booking_request(prompt)
        if hotel_name:
            st.session_state.booking_state["hotel_name"] = hotel_name
            st.session_state.booking_state["step"] = "room_selection"
            st.session_state.booking_state["active"] = True
            return f"Great! I'll help you book {hotel_name}. Please select a room type:", "room_selection"
        else:
            st.session_state.booking_state["step"] = "room_selection"
            st.session_state.booking_state["active"] = True
            return "I'll help you with the booking. Please select a room type:", "room_selection"
    
    elif current_step == "room_selection":
        room_types = get_room_types()
        selected_room = None
        
        for room in room_types:
            if room["type"].lower() in prompt.lower():
                selected_room = room
                break
        
        if selected_room:
            st.session_state.booking_state["room_type"] = selected_room["type"]
            st.session_state.booking_state["step"] = "date_selection"
            return f"Perfect! You've selected {selected_room['type']}. Now please provide your check-in and check-out dates (e.g., 'Check-in: 2025-08-01, Check-out: 2025-08-03'):", "date_selection"
        else:
            return "Please select one of the available room types:", "room_selection"
    
    elif current_step == "date_selection":
        # Simple date extraction (you can make this more sophisticated)
        st.session_state.booking_state["check_in"] = "2025-08-01"  # Default for demo
        st.session_state.booking_state["check_out"] = "2025-08-03"  # Default for demo
        st.session_state.booking_state["step"] = "guest_selection"
        return "Thanks! Now please tell me how many guests will be staying:", "guest_selection"
    
    elif current_step == "guest_selection":
        # Extract number of guests
        import re
        numbers = re.findall(r'\d+', prompt)
        if numbers:
            guests = int(numbers[0])
            st.session_state.booking_state["guests"] = guests
            st.session_state.booking_state["step"] = "confirmation"
            
            # Generate a random total price for demo purposes
            base_price = random.randint(120, 350)
            nights = 2
            total_price = base_price * nights
            st.session_state.booking_state["total_price"] = total_price
            
            return f"Perfect! Let me confirm your booking details:\n\n" \
                   f"🏨 Hotel: {st.session_state.booking_state.get('hotel_name', 'Selected Hotel')}\n" \
                   f"🛏️ Room: {st.session_state.booking_state['room_type']}\n" \
                   f"📅 Check-in: {st.session_state.booking_state['check_in']}\n" \
                   f"📅 Check-out: {st.session_state.booking_state['check_out']}\n" \
                   f"👥 Guests: {guests}\n" \
                   f"💰 Total Price: ${total_price:,} ({nights} nights)\n\n" \
                   f"Type 'confirm' to complete the booking or 'cancel' to cancel.", "confirmation"
        else:
            return "Please specify the number of guests (e.g., '2 guests'):", "guest_selection"
    
    elif current_step == "confirmation":
        if "confirm" in prompt.lower():
            # Generate booking confirmation
            booking_id = f"HTL{random.randint(100000, 999999)}"
            st.session_state.booking_state["booking_id"] = booking_id
            st.session_state.booking_state["step"] = "completed"
            
            return f"🎉 **Booking Confirmed!** 🎉\n\n" \
                   f"Your booking has been successfully processed!\n\n" \
                   f"**Booking Details:**\n" \
                   f"📋 Booking ID: {booking_id}\n" \
                   f"🏨 Hotel: {st.session_state.booking_state.get('hotel_name', 'Selected Hotel')}\n" \
                   f"🛏️ Room: {st.session_state.booking_state['room_type']}\n" \
                   f"📅 Check-in: {st.session_state.booking_state['check_in']}\n" \
                   f"📅 Check-out: {st.session_state.booking_state['check_out']}\n" \
                   f"👥 Guests: {st.session_state.booking_state['guests']}\n" \
                   f"💰 Total Paid: ${st.session_state.booking_state['total_price']:,}\n\n" \
                   f"📧 A confirmation email has been sent to your registered email address.\n" \
                   f"📱 You can use booking ID {booking_id} for any future inquiries.\n\n" \
                   f"Thank you for choosing our service! Have a wonderful stay! 🌟", "completed"
        elif "cancel" in prompt.lower():
            # Reset booking state
            st.session_state.booking_state = {
                "active": False,
                "hotel_name": "",
                "room_type": "",
                "check_in": "",
                "check_out": "",
                "guests": 0,
                "total_price": 0,
                "step": "initial"
            }
            return "Booking cancelled. How else can I help you today?", "initial"
        else:
            return "Please type 'confirm' to complete the booking or 'cancel' to cancel.", "confirmation"
    
    return "I'm not sure how to help with that. Can you please clarify?", current_step

async def call_agent(prompt, agent_type="search"):
    content = types.Content(role='user', parts=[types.Part(text=prompt)])
    final_response_text = "Sorry, I couldn't generate a response."
    
    runner = SEARCH_RUNNER if agent_type == "search" else BOOKING_RUNNER
    
    async for event in runner.run_async(user_id=USER_ID, session_id=SESSION_ID, new_message=content):
        if event.is_final_response():
            if event.content and event.content.parts:
                final_response_text = event.content.parts[0].text
            elif event.actions and event.actions.escalate:
                final_response_text = f"Agent escalated: {event.error_message or 'No specific message.'}"
            break
    return final_response_text

# --- Streamlit UI ---
st.markdown("""<style>
    [data-testid="stAppViewContainer"] {
        background:
            radial-gradient(circle at 12% 12%, rgba(96, 165, 250, 0.24), transparent 24rem),
            radial-gradient(circle at 88% 18%, rgba(52, 211, 153, 0.20), transparent 22rem),
            radial-gradient(circle at 50% 92%, rgba(186, 230, 253, 0.45), transparent 28rem),
            linear-gradient(135deg, #f8fbff 0%, #eef6ff 48%, #f0fdf4 100%);
    }
    [data-testid="stHeader"] { background: transparent; }
    .main .block-container { padding-top: 2rem; padding-bottom: 2rem; max-width: 1120px; }
    .app-header {
        background: linear-gradient(135deg, #0f172a 0%, #1d4ed8 58%, #059669 100%);
        border: 1px solid rgba(255, 255, 255, 0.25);
        border-radius: 22px;
        padding: 2rem 2.2rem;
        margin-bottom: 1.8rem;
        box-shadow: 0 24px 55px rgba(15, 23, 42, 0.18);
    }
    .app-header h1 { font-size: 2.35rem; font-weight: 800; color: #ffffff; letter-spacing: -0.04em; margin: 0; }
    .app-header p { color: #dbeafe; font-size: 1rem; max-width: 720px; margin-top: 0.65rem; margin-bottom: 0; line-height: 1.6; }
    .hero-pill {
        display: inline-block;
        padding: 0.35rem 0.75rem;
        border-radius: 999px;
        background: rgba(255, 255, 255, 0.16);
        color: #ecfeff;
        font-size: 0.72rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.11em;
        margin-bottom: 0.85rem;
    }
    .hotel-source { font-size: 0.75rem; color: #9ca3af; margin-top: 0.1rem; }
    .section-label { font-size: 0.72rem; font-weight: 800; color: #2563eb; text-transform: uppercase; letter-spacing: 0.12em; margin-bottom: 0.75rem; margin-top: 1.5rem; padding-bottom: 0.4rem; border-bottom: 1px solid rgba(37, 99, 235, 0.18); }
    .room-card { background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 0.85rem 1.1rem; margin-bottom: 0.5rem; }
    .room-card-title { font-weight: 600; font-size: 0.92rem; color: #111827; }
    .room-card-desc { font-size: 0.8rem; color: #6b7280; margin-top: 0.15rem; }
    div[data-testid="stVerticalBlockBorderWrapper"] {
        background: #ffffff;
        border-color: rgba(148, 163, 184, 0.35);
        box-shadow: 0 12px 32px rgba(15, 23, 42, 0.08);
    }
    div[data-testid="stVerticalBlockBorderWrapper"] h1,
    div[data-testid="stVerticalBlockBorderWrapper"] h2,
    div[data-testid="stVerticalBlockBorderWrapper"] h3,
    div[data-testid="stVerticalBlockBorderWrapper"] p,
    div[data-testid="stVerticalBlockBorderWrapper"] span,
    div[data-testid="stVerticalBlockBorderWrapper"] label {
        color: #0f172a !important;
    }
    div[data-testid="stVerticalBlockBorderWrapper"] [data-testid="stCaptionContainer"] p {
        color: #475569 !important;
    }
    div[data-testid="stMetric"] label,
    div[data-testid="stMetric"] div {
        color: #0f172a !important;
    }
    div[data-testid="stMetricValue"] {
        color: #047857 !important;
    }
    .stChatMessage {
        background: rgba(255, 255, 255, 0.78);
        border-radius: 16px;
        border: 1px solid rgba(226, 232, 240, 0.9);
    }
    .stChatMessage p,
    .stChatMessage h1,
    .stChatMessage h2,
    .stChatMessage h3,
    .stChatMessage span {
        color: #0f172a !important;
    }
    section[data-testid="stSidebar"] { background: linear-gradient(180deg, #ffffff 0%, #eef4ff 100%); }
    #MainMenu { visibility: hidden; }
    footer { visibility: hidden; }
</style>""", unsafe_allow_html=True)

st.markdown("""
<div class="app-header">
    <div class="hero-pill">AI hotel concierge</div>
    <h1>Hotel Reservation Agent</h1>
    <p>Search, compare, and reserve hotels across major booking platforms with clean pricing insights and a guided booking flow.</p>
</div>
""", unsafe_allow_html=True)

# Initialize chat history in session state
if "messages" not in st.session_state:
    st.session_state.messages = []


def render_hotel_card(hotel: Dict, idx: int, show_all_prices: bool, key_prefix: str = "") -> None:
    with st.container(border=True):
        details_col, price_col, action_col = st.columns([4, 1.4, 1.2], vertical_alignment="center")
        with details_col:
            st.caption(f"#{idx} recommended option")
            st.markdown(f"### {hotel['hotel_name']}")
            st.write(hotel["location"])
            if hotel.get("rating", 0) > 0:
                st.caption(f"Guest rating: {hotel['rating']}/10")
            if hotel.get("link"):
                st.link_button(f"View on {hotel['price_source']}", hotel["link"])

        with price_col:
            st.metric("Nightly rate", f"${hotel['price']:,}")
            st.caption(f"via {hotel['price_source']}")

        with action_col:
            if st.button("Reserve", key=f"{key_prefix}book_{idx}", type="primary", use_container_width=True):
                st.session_state.booking_state["hotel_name"] = hotel['hotel_name']
                st.session_state.booking_state["active"] = True
                st.session_state.booking_state["step"] = "room_selection"
                st.rerun()

    if show_all_prices and hotel.get("all_prices"):
        with st.expander("Compare all platforms"):
            for site, details in hotel["all_prices"].items():
                if details["available"]:
                    st.markdown(f"**{site}** — ${details['price']:,}")
                else:
                    st.markdown(f"{site} — not available")


def render_room_types() -> None:
    st.markdown('<div class="section-label">Available Room Categories</div>', unsafe_allow_html=True)
    for room in get_room_types():
        st.markdown(f"""
        <div class="room-card">
            <div class="room-card-title">{room['type']}</div>
            <div class="room-card-desc">{room['description']}</div>
        </div>
        """, unsafe_allow_html=True)


def render_summary(available_hotels: List[Dict]) -> None:
    min_price = min(h['price'] for h in available_hotels)
    max_price = max(h['price'] for h in available_hotels)
    st.markdown('<div class="section-label">Results Summary</div>', unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    c1.metric("Properties Found", len(available_hotels))
    c2.metric("Lowest Rate / night", f"${min_price:,}")
    c3.metric("Highest Rate / night", f"${max_price:,}")


def render_hotel_results(hotels_data: List[Dict], show_all_prices: bool, key_prefix: str = "") -> None:
    available = [h for h in hotels_data if h['price'] > 0]
    unavailable = [h for h in hotels_data if h['price'] == 0]

    if available:
        st.markdown('<div class="section-label">Results — sorted by lowest rate</div>', unsafe_allow_html=True)
        for i, hotel in enumerate(available, 1):
            render_hotel_card(hotel, i, show_all_prices, key_prefix)
        render_summary(available)

    for hotel in unavailable:
        st.caption(f"{hotel['hotel_name']} — no rates available from tracked platforms")


with st.sidebar:
    st.markdown("### Settings")
    show_all_prices = st.checkbox("Show all platform prices", value=False)
    max_hotels = st.slider("Max results", min_value=3, max_value=15, value=8)

    st.markdown("---")
    st.markdown("### Booking Status")
    if st.session_state.booking_state["active"]:
        step_label = st.session_state.booking_state['step'].replace('_', ' ').title()
        st.info(f"In progress — {step_label}")
        if st.session_state.booking_state["hotel_name"]:
            st.markdown(f"**Hotel:** {st.session_state.booking_state['hotel_name']}")
        if st.session_state.booking_state["room_type"]:
            st.markdown(f"**Room:** {st.session_state.booking_state['room_type']}")
        if st.button("Cancel Booking", type="secondary"):
            st.session_state.booking_state = {
                "active": False, "hotel_name": "", "room_type": "",
                "check_in": "", "check_out": "", "guests": 0,
                "total_price": 0, "step": "initial"
            }
            st.rerun()
    else:
        st.success("Ready")

# Display chat messages from history on app rerun
for message_idx, message in enumerate(st.session_state.messages):
    with st.chat_message(message["role"]):
        if message["type"] == "text":
            st.write(message["content"])
        elif message["type"] == "booking":
            st.markdown(message["content"])
            if "room_selection" in message.get("step", ""):
                render_room_types()
        elif message["type"] == "hotels":
            text_output = message["content"].get("text")
            hotels_data = message["content"].get("hotels")
            if text_output:
                st.caption(text_output)
            if hotels_data:
                render_hotel_results(hotels_data, show_all_prices, key_prefix=f"hist_{message_idx}_")
            elif not text_output:
                st.warning("No results found for this query.")
        elif message["type"] == "error":
            st.error(message["content"])

if prompt := st.chat_input("e.g., hotels in Miami under $200  ·  Book The Ritz-Carlton"):
    st.session_state.messages.append({"role": "user", "type": "text", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    with st.chat_message("assistant"):
        if prompt.lower() == "hi":
            greeting = "Hello — I can help you search for hotels and manage your reservation. What are you looking for?"
            st.write(greeting)
            st.session_state.messages.append({"role": "assistant", "type": "text", "content": greeting})

        elif detect_booking_intent(prompt) or st.session_state.booking_state["active"]:
            current_step = st.session_state.booking_state["step"]
            if detect_booking_intent(prompt) and not st.session_state.booking_state["active"]:
                current_step = "initial"

            response_text, next_step = process_booking_step(prompt, current_step)
            st.session_state.booking_state["step"] = next_step

            if next_step == "completed":
                st.session_state.booking_state["active"] = False

            st.markdown(response_text)

            if next_step == "room_selection":
                render_room_types()

            st.session_state.messages.append({
                "role": "assistant",
                "type": "booking",
                "content": response_text,
                "step": next_step
            })

        else:
            with st.spinner("Searching for hotels..."):
                response_text = asyncio.run(call_agent(prompt, "search"))

            try:
                cleaned = response_text.replace("```json", "").replace("```", "").strip()
                response_json = json.loads(cleaned)

                text_output = response_json.get("text")
                hotels = response_json.get("hotels")

                processed_hotel_data = {"text": text_output, "hotels": []}

                if text_output:
                    st.caption(text_output)

                if hotels:
                    with st.spinner("Comparing rates across platforms..."):
                        enhanced = get_best_hotel_deals(hotels)
                        enhanced = enhanced[:max_hotels]
                        processed_hotel_data["hotels"] = enhanced

                    render_hotel_results(enhanced, show_all_prices)

                elif text_output:
                    st.warning("The search returned a summary but no hotel records. Try the query again or make it more specific, for example: hotels in Los Angeles under $200 near Hollywood.")

                elif not text_output:
                    st.warning("No results found. Try refining your search query.")

                st.session_state.messages.append({
                    "role": "assistant",
                    "type": "hotels",
                    "content": processed_hotel_data
                })

            except json.JSONDecodeError:
                st.markdown(response_text)
                st.session_state.messages.append({"role": "assistant", "type": "text", "content": response_text})
            except Exception as e:
                error_message = f"An error occurred: {e}"
                st.error(error_message)
                st.code(response_text)
                st.session_state.messages.append({"role": "assistant", "type": "error", "content": error_message})
