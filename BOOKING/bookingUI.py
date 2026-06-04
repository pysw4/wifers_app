import streamlit as st
import pandas as pd
import geopandas as gpd
from datetime import date, datetime, timedelta
import uuid
from predictor import PREDICTORFUNCTION

# initialise state
if 'bookings' not in st.session_state:
    st.session_state.bookings = []
if 'show_alternatives' not in st.session_state:
    st.session_state.show_alternatives = False
if 'alternatives_result' not in st.session_state:
    st.session_state.alternatives_result = []
if 'best_slot' not in st.session_state:
    st.session_state.best_slot = None 

#DATA
@st.cache_data
def load_data():
    # 注意: 请将路径替换为实际 parquet 文件路径
    df = pd.read_parquet(r"../meme_clean.parquet")
    # 预处理：缓存 dayofweek，避免每次查询重新解析 timestamp
    df['dayofweek'] = pd.to_datetime(df['timestamp']).dt.dayofweek
    # 预处理：strip associated_device_name 中的空白
    df['associated_device_name'] = df['associated_device_name'].str.strip()
    return df

@st.cache_data
def load_geo():
    # 注意: 请将路径替换为实际 geojson 文件路径
    return gpd.read_file(r'../geolocation_package/data/aps_geolocalizados_wgs84.geojson')

df_clean = load_data()
geo      = load_geo()


PERF_RANK = {'Critical':0, 'Poor':1, 'Fair':2, 'Good':3, 
             'Excellent':4, 'Excellent+':5, 'Excellent++':6}
room_to_ap = (
    geo[['USER_Espai', 'USER_NOM_A', 'USER_EDIFI', 'Num_Planta']]
    .dropna(subset=['USER_Espai', 'USER_NOM_A'])
    .set_index('USER_Espai')
)
room_lookup = {}
for _, row in geo.iterrows():
    room_code = str(row['USER_Espai']).strip().upper()
    room_lookup[room_code] = {
        'ap_name':  str(row['USER_NOM_A']).strip().upper(),
        'building': row['USER_EDIFI'],
        'floor':    row['Num_Planta']
    }

#FUNCTIONS
def get_ap(room_code):
    return room_lookup.get(room_code.strip().upper())
def get_all_bookings(bookings: list):
    return bookings

def create_booking(bookings,teacher_id, room_code, date, start_hour, end_hour, n_students, min_performance, predicted_performance):
    ap_info = get_ap(room_code)
    
    booking = {
        'booking_id':    str(uuid.uuid4())[:8].upper(),
        'teacher_id':    teacher_id,
        'room_code':     room_code,
        'date':          date,
        'start_hour':    start_hour,
        'end_hour':      end_hour,
        'n_students':    n_students,
        'min_performance': min_performance,
        'predicted_performance': predicted_performance,
        'ap_name':      ap_info['ap_name'],
    }
    
    bookings.append(booking)
    return booking

def check_availability(bookings, room_code, date, start_hour, end_hour):
    room_code_upper = room_code.strip().upper()

    for book in bookings:
        if book['room_code'] != room_code_upper or book['date'] != date:
            continue
        if not (end_hour <= book['start_hour'] or start_hour >= book['end_hour']):
            return False, book
        
    return True, None

def cancel_booking(bookings, booking_id):
    for i, book in enumerate(bookings):
        if book['booking_id'] == booking_id:
            bookings.pop(i) #we remove it
            return True
        
    return False

def get_bookings_room(bookings, room_code, date):
    return [book for book in bookings if book['room_code']==room_code and book['date']==date]
    
def get_bookings_day(bookings, date):
    return [book for book in bookings if book['date']==date]

def get_bookings_teacher(bookings, teacher_id):
    return [book for book in bookings if book['teacher_id'] ==teacher_id]

def predict_for_room(room_code, date,start_hour,end_hour, n_students, df_clean):
    # as the prediction only works well till the 5 hours:
    booking_dt = datetime.strptime(f"{date} {start_hour:02d}:00", "%Y-%m-%d %H:%M")
    hours_until = (booking_dt - datetime.now()).total_seconds() / 3600

    if hours_until > 5:
        return {
            'ap_name':     get_ap(room_code)['ap_name'],
            'performance': None,
            'predictions': None,
            'warning':     f"Prediction not available — booking is {hours_until:.0f}h away (max 5h)"
        }


    ap_info = get_ap(room_code)
    if ap_info is None:
        return None
    ap_name = ap_info['ap_name']

    day_of_week = pd.Timestamp(date).dayofweek
    hours = list(range(start_hour, end_hour))

    input_df = df_clean[                          
        (df_clean['associated_device_name'] == ap_name) &
        (df_clean['hour'].isin(hours)) &
        (df_clean['dayofweek'] == day_of_week)
    ].copy()

    if len(input_df) == 0:
        return None
        
    input_df['client_count'] = n_students
    input_df['overloaded']   = n_students > 50
    
    result = PREDICTORFUNCTION(input_df)

    worst = min(result, key=lambda x: PERF_RANK.get(x[1], 0))  #pick the worst prediction across all rows, teacher cares about the worst case in the slot.

    return {
        'performance': worst[1], 
        'predictions': result,
        'ap_name':     ap_name,
        'warning':     None
    }

def show_availability (bookings, room_code, booking_date):

    ap_info = get_ap(room_code)
    if ap_info is None:
        return None
    
    room_code_upper = room_code.strip().upper()
    date_str  = str(booking_date)
    booked_ranges = [
        (b['start_hour'], b['end_hour'])
        for b in bookings
        if b['room_code'] == room_code_upper and b['date'] == date_str
    ]

    def is_booked(h):
        return any(s <= h < e for s, e in booked_ranges)

    hours = list(range(7, 22))
    cols  = st.columns(len(hours))
    for col, h in zip(cols, hours):
        if is_booked(h):
            col.markdown(
                f"<div style='background:#ff4b4b;color:white;text-align:center;"
                f"border-radius:6px;padding:6px 0;font-size:12px'>"
                f"<b>{h:02d}</b><br>🔴</div>",
                unsafe_allow_html=True
            )
        else:
            col.markdown(
                f"<div style='background:#21c354;color:white;text-align:center;"
                f"border-radius:6px;padding:6px 0;font-size:12px'>"
                f"<b>{h:02d}</b><br>🟢</div>",
                unsafe_allow_html=True
            )

def suggest_best_slot(room_code, booking_date, hours, n_students, df_clean, bookings):
    results = []
    for start in range(7, 23 - hours):
        end = start + hours
        available, _ = check_availability(bookings, room_code, booking_date, start, end)
        if not available:
            continue
        pred = predict_for_room(room_code, booking_date, start, end, n_students, df_clean)
        if pred is None or pred['warning']:
            continue
        results.append((start, end, pred['performance']))

    if not results:
        return None
    return max(results, key=lambda x: PERF_RANK.get(x[2], 0))

def suggest_alternatives(room_code, booking_date, start_hour, end_hour,n_students, min_perf, df_clean, bookings):
    #will find rooms on the same floor whose AP has better performance and is available

    current = room_lookup.get(room_code.strip().upper())
    if current is None:
        return []
    
    area = [code for code, info in room_lookup.items() if info['building'] == current['building']  and info['floor']== current['floor'] and code!= room_code.strip().upper()]

    candidates = []

    visited = set()

    for a in area:
        ap_info = get_ap(a)
        ap = ap_info['ap_name']
        if ap in visited:
            continue
        available, _ = check_availability(bookings, a, booking_date, start_hour, end_hour)
        if not available:
            continue
        pred = predict_for_room(a, booking_date, start_hour, end_hour, n_students, df_clean)
        if pred is None or pred['warning']:
            continue
        if PERF_RANK.get(pred['performance'], 0) >= PERF_RANK[min_perf]:
            candidates.append((a, pred['performance']))
            visited.add(ap)
    
    return sorted(candidates, key=lambda x: PERF_RANK.get(x[1], 0), reverse=True)

#START-----------------------------------------------------------
#looking at my bookings
with st.sidebar:
    st.header("My bookings")
    teacher_id_sidebar = st.session_state.get('_teacher_id', '')
    if not teacher_id_sidebar:
        st.caption("Enter your Teacher ID to see them.")
    
    else:
        my_bookings = get_bookings_teacher(st.session_state.bookings, teacher_id_sidebar)
        if not my_bookings:
            st.caption("No bookings yet, good moment to book your first one ;)")
        
        for book in my_bookings:

            with st.expander(f"{book['room_code']} // {book['date']} // {book['start_hour']:02d}–{book['end_hour']:02d}"):
                st.write(f"AP: {book['ap_name']}")
                st.write(f"Students: {book['n_students']}")
                st.write(f"Min performance: {book['min_performance']}")
                st.write(f"Performance: {book['predicted_performance']}")
                st.write(f"Booking ID: {book['booking_id']}")
                if st.button("Cancel this booking", key=f"cancel_{book['booking_id']}"):
                    cancel_booking(st.session_state.bookings, book['booking_id'])
                    st.success("Booking cancelled.")
                    st.rerun()

#MAIN
st.title("WiFERS Room Booking")

teacher_id  = st.text_input("Teacher ID")
room_code   = st.text_input("Room code").strip().upper()
booking_date = st.date_input("Date", min_value=date.today())
start_hour  = st.selectbox("Start", range(7, 22), format_func=lambda h: f"{h:02d}:00")
end_hour    = st.selectbox("End",   range(8, 23), format_func=lambda h: f"{h:02d}:00")
n_students  = st.slider("Students", 1, 120, 30)
min_perf    = st.selectbox("Minimum acceptable performance", 
                            ['Fair', 'Good', 'Excellent'])

# apply suggested slot if one has chosen
if st.session_state.best_slot:
    s, e, _ = st.session_state.best_slot
    st.info(f"Suggested slot pre-filled: **{s:02d}:00 – {e:02d}:00** — adjust above if needed.")

#show calendar
if room_code:
    st.markdown("Slot availability")
    show_availability(st.session_state.bookings, room_code, booking_date)
    st.markdown("---")

#check i book
if st.button("Check & book"):
    if not teacher_id:
        st.error("Please enter a teacher ID")
    elif end_hour <= start_hour:
        st.error("End time must be after start time")
    
    else:
        available, conflict = check_availability(
            st.session_state.bookings, room_code, 
            str(booking_date), start_hour, end_hour
        )
        if not available:
            st.error(f"Room already booked from {conflict['start_hour']:02d}:00 to {conflict['end_hour']:02d}:00")
        
        else:

            result = predict_for_room(
                room_code, str(booking_date), 
                start_hour, end_hour, n_students, df_clean
            )
            if result is None:
                st.error("No data for this room and time slot")
            
            elif result['warning']:
                st.warning(result['warning'])

                create_booking(st.session_state.bookings, teacher_id, room_code,
                               str(booking_date), start_hour, end_hour, 
                               n_students, min_perf, 0)
                st.success("Booking created BUT not prediction available")

            else:
                predicted = result['performance']
                ap_info = get_ap(room_code)
                ap_name = ap_info['ap_name']

                if PERF_RANK[predicted] >= PERF_RANK[min_perf]:
                    st.success(f"Performance predicted for {ap_name}: {predicted}")
                    create_booking(st.session_state.bookings, teacher_id, room_code,
                                   str(booking_date), start_hour, end_hour,
                                   n_students, min_perf, predicted)
                    st.success(f" Booking confirmed {teacher_id}! \n Room: {room_code} \n AP you will be connected to: {ap_name} \n Date: {str(booking_date)} \n Start - End: {start_hour}-{end_hour} \n Students: {n_students}")
                else:
                    st.warning(f"Predicted performance for {ap_name}: {predicted}, below your minimum ({min_perf}). Consider a different room or time.")
                    st.session_state['_alt_params'] = dict(
                        room_code=room_code, booking_date=str(booking_date),
                        start_hour=start_hour, end_hour=end_hour,
                        n_students=n_students, min_perf=min_perf
                    )
                    st.session_state.show_alternatives = True
#alternatives button                    
if st.session_state.show_alternatives and '_alt_params' in st.session_state:                    
    if st.button("Suggest alternative room"):
        with st.spinner("Checking nearby rooms..."):
            alternatives = suggest_alternatives(room_code, str(booking_date),start_hour, end_hour, n_students, min_perf, df_clean, st.session_state.bookings)
            if not alternatives:
                st.error("We are afraid there are no available rooms on the same floor with sufficient performance.")
                
            else:
                for alternative_code, alternative_performance in alternatives:
                    ap_info = get_ap(alternative_code)
                    ap_name = ap_info['ap_name']
                    st.write(f"**{alternative_code}** · AP: `{ap_info['ap_name']}` " f"· Floor {ap_info['floor']} · Predicted: **{alternative_performance}**")


#recommendation
st.markdown("Not sure when to book? 😏 Let us help you!")
duration = st.number_input("Session length (hours)", min_value=1, max_value=6, value=2)

if st.button("Suggest best time slot"):
    if not room_code:
        st.error("Enter a room code first")
    else:
        with st.spinner("Searching for the best slot only for you 🤫..."):
            best = suggest_best_slot(
                room_code, str(booking_date),
                duration, n_students, df_clean,
                st.session_state.bookings
            )
        if best is None:
            st.warning("No available slots with prediction for this room and time😔.")
        else:
            start, end, perf = best
            st.success(
                f"Best slot: **{start:02d}:00 – {end:02d}:00** "
                f"· Predicted performance: **{perf}**"
            )
            if st.button("We recommend you to use this slot 😉", key="use_suggested"):
                st.session_state.suggested_slot = (start, end)
                st.rerun()



