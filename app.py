import streamlit as st
import pandas as pd
import gspread
from datetime import date, datetime
import pytz
import math
from google.oauth2.service_account import Credentials
from streamlit_geolocation import streamlit_geolocation

st.set_page_config(page_title="Daily Activity Tracker", layout="wide") 

# --- OFFICE EXACT COORDINATES (Decimal Degrees) ---
OFFICE_LAT = 13.034167
OFFICE_LON = 80.212861

# --- HAVERSINE DISTANCE CALCULATOR ---
def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371000  # Radius of Earth in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def get_current_ist_time():
    ist_timezone = pytz.timezone('Asia/Kolkata')
    return datetime.now(ist_timezone).strftime("%I:%M %p")

# --- 1. GLOBAL GOOGLE SHEETS CONNECTION ---
@st.cache_resource
def get_worksheets():
    secret_dict = dict(st.secrets["gcp_service_account"])
    client = gspread.service_account_from_dict(secret_dict)
    sh = client.open("Office_Timesheet_App_Data")
    
    try:
        return {
            "Client_Master": sh.worksheet("Client_Master"),
            "Task_Master": sh.worksheet("Task_Master"),
            "Employee_Master": sh.worksheet("Employee_Master"),
            "Daily_Logs": sh.worksheet("Daily_Logs"),
            "Attendance_Log": sh.worksheet("Attendance_Log") 
        }
    except gspread.exceptions.WorksheetNotFound:
        st.error("⚠️ CRITICAL: Could not find the 'Attendance_Log' tab. Please create it in your Google Sheet!")
        st.stop()

# --- 2. FETCH MASTER DATA ---
@st.cache_data(ttl=600)
def get_master_data():
    ws = get_worksheets()
    clients_records = ws["Client_Master"].get_all_records()
    tasks_records = ws["Task_Master"].get_all_records()
    emp_records = ws["Employee_Master"].get_all_records()
    
    active_employees = [emp for emp in emp_records if str(emp.get('Status', 'Active')).strip().lower() == 'active']
    tasks_list = [row['Task_Category'] for row in tasks_records]
    
    clients_list = []
    client_coords = {} 
    
    for row in clients_records:
        # Ensures DIN is always appended to the client name from the master data
        name = f"{row['Client_Name']} (DIN: {row['DIN']})" if row.get('DIN') else row['Client_Name']
        clients_list.append(name)
        
        lat = str(row.get('Latitude', '')).strip()
        lon = str(row.get('Longitude', '')).strip()
        
        try:
            client_coords[name] = (float(lat) if lat else None, float(lon) if lon else None)
        except ValueError:
            client_coords[name] = (None, None) 
    
    return clients_list, tasks_list, active_employees, client_coords

# --- 3. LIVE ATTENDANCE ENGINE ---
def get_attendance_status(check_date, emp_name):
    ws = get_worksheets()
    records = ws["Attendance_Log"].get_all_values() 
    for row in records:
        if len(row) >= 4 and row[0] == str(check_date) and row[1] == emp_name:
            if row[3] != "": 
                return "punched_out", row[2], row[3]
            else:
                return "punched_in", row[2], None
    return "not_punched_in", None, None

def punch_in(check_date, emp_name, in_time):
    ws = get_worksheets()
    ws["Attendance_Log"].append_row([str(check_date), emp_name, in_time, ""])

def punch_out(check_date, emp_name, out_time):
    ws = get_worksheets()
    records = ws["Attendance_Log"].get_all_values()
    for i, row in enumerate(records):
        if len(row) >= 2 and row[0] == str(check_date) and row[1] == emp_name:
            ws["Attendance_Log"].update_cell(i + 1, 4, out_time) 
            break

def get_todays_tasks(check_date, emp_name):
    ws = get_worksheets()
    records = ws["Daily_Logs"].get_all_records()
    df = pd.DataFrame(records)
    if not df.empty:
        df['Date'] = df['Date'].astype(str)
        return df[(df['Date'] == str(check_date)) & (df['Employee_ID'] == emp_name)]
    return pd.DataFrame()

clients, tasks, employees, client_coords = get_master_data()
emp_dict = {f"{emp['Full_Name']} ({emp['Employee_ID']})": str(emp.get('Password', '1234')) for emp in employees}
emp_names = list(emp_dict.keys())

# --- 4. SESSION STATE ---
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'is_admin' not in st.session_state:
    st.session_state.is_admin = False
if 'current_user' not in st.session_state:
    st.session_state.current_user = ""

# --- 5. LOGIN PORTAL ---
if not st.session_state.logged_in:
    st.title("🔐 Office Portal Login")
    tab1, tab2 = st.tabs(["Employee Login", "Admin Login"])
    
    with tab1:
        with st.form("login_form"):
            selected_emp = st.selectbox("Select Employee", emp_names)
            emp_password = st.text_input("Password / PIN", type="password")
            if st.form_submit_button("Login", type="primary", use_container_width=True):
                if emp_password == emp_dict[selected_emp]:
                    st.session_state.logged_in = True
                    st.session_state.is_admin = False
                    st.session_state.current_user = selected_emp
                    st.rerun() 
                else:
                    st.error("Incorrect Password.")
                        
    with tab2:
        with st.form("admin_login_form"):
            admin_pass = st.text_input("Admin Password", type="password")
            if st.form_submit_button("Login as Admin", type="primary", use_container_width=True):
                if admin_pass == "admin123": 
                    st.session_state.logged_in = True
                    st.session_state.is_admin = True
                    st.session_state.current_user = "Administrator"
                    st.rerun()
                else:
                    st.error("Incorrect Admin Password.")

# --- 6. ADMIN DASHBOARD VIEW ---
elif st.session_state.is_admin:
    st.sidebar.write("👑 **Admin Dashboard**")
    
    st.sidebar.markdown("---")
    st.sidebar.write("**Admin Controls**")
    if st.sidebar.button("🔄 Sync Master Data Now", use_container_width=True):
        get_master_data.clear()
        st.sidebar.success("Lists updated successfully!")
        st.rerun()
        
    st.sidebar.markdown("---")
    if st.sidebar.button("Logout", type="secondary"):
        st.session_state.logged_in = False
        st.session_state.is_admin = False
        st.rerun()
        
    st.title("📊 Office Operations Dashboard")
    st.divider()
    
    try:
        ws = get_worksheets()
        att_df = pd.DataFrame(ws["Attendance_Log"].get_all_records())
        log_df = pd.DataFrame(ws["Daily_Logs"].get_all_records())
        
        st.subheader("🏢 Live Attendance (Today)")
        if not att_df.empty:
            att_df['Date'] = att_df['Date'].astype(str)
            today_att = att_df[att_df['Date'] == str(date.today())]
            st.dataframe(today_att, use_container_width=True)
        else:
            st.info("No attendance records yet.")
            
        st.markdown("---")
        
        if not log_df.empty:
            log_df['Date'] = pd.to_datetime(log_df['Date'])
            log_df['Conveyance_₹'] = pd.to_numeric(log_df['Conveyance_₹'], errors='coerce').fillna(0)
            
            st.subheader("Filter Task Data")
            col1, col2, col3, col4 = st.columns(4)
            with col1: start_date = st.date_input("Start Date", log_df['Date'].min())
            with col2: end_date = st.date_input("End Date", log_df['Date'].max())
            with col3: emp_filter = st.multiselect("Filter by Employee", options=log_df['Employee_ID'].unique())
            with col4: client_filter = st.multiselect("Filter by Client", options=log_df['Client_ID'].unique())
            
            mask = (log_df['Date'].dt.date >= start_date) & (log_df['Date'].dt.date <= end_date)
            filtered_df = log_df.loc[mask]
            if emp_filter: filtered_df = filtered_df[filtered_df['Employee_ID'].isin(emp_filter)]
            if client_filter: filtered_df = filtered_df[filtered_df['Client_ID'].isin(client_filter)]
            
            st.markdown("---")
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Total Activities", len(filtered_df))
            m2.metric("Total Conveyance", f"₹{filtered_df['Conveyance_₹'].sum():.2f}")
            m3.metric("Unique Clients", filtered_df['Client_ID'].nunique())
            m4.metric("Active Employees", filtered_df['Employee_ID'].nunique())
            
            st.markdown("---")
            
            col_chart1, col_chart2 = st.columns(2)
            with col_chart1:
                st.write("**Conveyance by Employee**")
                conv_by_emp = filtered_df.groupby('Employee_ID')['Conveyance_₹'].sum().reset_index()
                if not conv_by_emp.empty: st.bar_chart(conv_by_emp, x='Employee_ID', y='Conveyance_₹')
            with col_chart2:
                st.write("**Work Location Breakdown**")
                loc_counts = filtered_df['Work_Location'].value_counts()
                st.bar_chart(loc_counts)
                
            st.markdown("---")
            
            st.subheader("Raw Data View")
            display_df = filtered_df.copy()
            display_df['Date'] = display_df['Date'].dt.strftime('%Y-%m-%d')
            
            csv_export = display_df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Export Filtered Data for Payroll (CSV)",
                data=csv_export,
                file_name=f"Timesheet_Export_{start_date}_to_{end_date}.csv",
                mime="text/csv",
            )
            
            st.dataframe(display_df, use_container_width=True)
            
    except Exception as e:
        st.error(f"Error loading dashboard: {e}")

# --- 7. THE EMPLOYEE LIVE ENTRY VIEW ---
else:
    st.sidebar.write(f"👤 Logged in as: **{st.session_state.current_user}**")
    
    with st.sidebar.expander("⚙️ Settings & Security"):
        st.write("**Change Your PIN**")
        new_pin = st.text_input("New PIN", type="password", key="new_pin")
        confirm_pin = st.text_input("Confirm New PIN", type="password", key="confirm_pin")
        
        if st.button("Update PIN", use_container_width=True):
            if new_pin and new_pin == confirm_pin:
                try:
                    emp_id = st.session_state.current_user.split("(")[-1].strip(")")
                    ws = get_worksheets()
                    cell = ws["Employee_Master"].find(emp_id)
                    if cell:
                        header = ws["Employee_Master"].row_values(1)
                        if "Password" in header:
                            pwd_col = header.index("Password") + 1
                            ws["Employee_Master"].update_cell(cell.row, pwd_col, new_pin)
                            st.success("PIN updated successfully!")
                            get_master_data.clear() 
                        else:
                            st.error("Error: 'Password' column not found in Master Sheet.")
                except Exception as e:
                    st.error(f"Failed to update PIN: {e}")
            else:
                st.error("PINs do not match or are empty.")

    if st.sidebar.button("Logout", type="secondary"):
        st.session_state.logged_in = False
        st.session_state.current_user = ""
        st.rerun()

    st.title("Live Activity Tracker")
    current_date = date.today()
    st.write(f"**Date:** {current_date}")
    st.divider()
    
    status, in_time, out_time = get_attendance_status(current_date, st.session_state.current_user)

    # PHASE 1: NOT PUNCHED IN
    if status == "not_punched_in":
        st.warning("You have not punched in for the day yet.")
        st.subheader("Start Your Shift")
        st.write("Click the button below to instantly clock in. The system will record your exact start time.")
        
        if st.button("⏱️ Punch IN Now", type="primary", use_container_width=True):
            auto_in_time = get_current_ist_time()
            punch_in(current_date, st.session_state.current_user, auto_in_time)
            st.rerun()

    # PHASE 2: ACTIVE SHIFT (Can log tasks)
    elif status == "punched_in":
        st.success(f"🟢 **Active Shift:** Punched In at {in_time}")
        
        with st.container(border=True):
            st.subheader("Log a Completed Task")
            c_client = st.selectbox("Select Client", clients)
            c_tasks = st.multiselect("Select Task(s) Performed", tasks)
            c_desc = st.text_area("Detailed Task Description")
            c_loc = st.radio("Work Location", ["Office", "Client Place"], horizontal=True)
            
            c_visit_loc = ""
            c_conv = 0
            
            if c_loc == "Client Place":
                c_visit_loc = st.selectbox("Client Location Visited", clients)
                c_conv = st.number_input("Conveyance Claimed (₹)", min_value=0)
                
            # --- NEW: Location Grabber is always visible to verify both Office and Client ---
            st.write("**📍 GPS Verification Required**")
            st.info("Please click the button below to capture your location before submitting your task.")
            user_location = streamlit_geolocation()
                
            if st.button("➕ Submit Task", type="primary"):
                if not c_tasks or not c_desc:
                    st.error("Tasks and Description are required.")
                elif c_loc == "Client Place" and not c_visit_loc:
                    st.error("Please select Client Location Visited.")
                elif user_location is None or user_location.get('latitude') is None:
                    st.error("⚠️ Please capture your GPS location using the button above.")
                else:
                    is_valid_location = True
                    final_visit_loc_str = c_visit_loc if c_loc == "Client Place" else "Office"
                    user_lat = user_location['latitude']
                    user_lon = user_location['longitude']
                    
                    # 1. GEO-FENCE FOR OFFICE (100 Meters)
                    if c_loc == "Office":
                        distance_meters = calculate_distance(user_lat, user_lon, OFFICE_LAT, OFFICE_LON)
                        if distance_meters > 100:
                            st.error(f"❌ Location Verification Failed: You are {int(distance_meters)} meters away from the registered Office.")
                            is_valid_location = False
                            
                    # 2. GEO-FENCE FOR CLIENT PLACE (200 Meters)
                    elif c_loc == "Client Place":
                        target_lat, target_lon = client_coords.get(c_visit_loc, (None, None))
                        
                        if target_lat is None or target_lon is None:
                            # Graceful Bypass
                            final_visit_loc_str += " (Geo-Fence Skipped: Coordinates Missing)"
                        else:
                            distance_meters = calculate_distance(user_lat, user_lon, target_lat, target_lon)
                            if distance_meters > 200:
                                st.error(f"❌ Location Verification Failed: You are {int(distance_meters)} meters away from the client's registered office.")
                                is_valid_location = False
                    
                    if is_valid_location:
                        tasks_string = ", ".join(c_tasks)
                        row_data = [str(current_date), st.session_state.current_user, "-", "-", c_loc, c_client, tasks_string, c_desc, final_visit_loc_str, c_conv]
                        get_worksheets()["Daily_Logs"].append_row(row_data)
                        st.success("Task Logged Successfully!")
                        st.rerun()

        st.subheader("📋 Your Tasks Today")
        todays_df = get_todays_tasks(current_date, st.session_state.current_user)
        if not todays_df.empty:
            view_df = todays_df.drop(columns=['In_Time', 'Out_Time', 'Employee_ID', 'Date'], errors='ignore')
            st.dataframe(view_df, use_container_width=True)
        else:
            st.info("You haven't logged any tasks yet today.")
            
        st.divider()
        
        st.subheader("End Your Shift")
        st.write("Ready to leave? Click below to instantly clock out and lock your timesheet for today.")
        if st.button("🛑 Punch OUT Now (Locks Day)", type="primary", use_container_width=True):
            auto_out_time = get_current_ist_time()
            punch_out(current_date, st.session_state.current_user, auto_out_time)
            st.rerun()

    # PHASE 3: SHIFT COMPLETED (Day Locked)
    elif status == "punched_out":
        st.error(f"🔴 **Shift Completed:** Punched In at {in_time} | Punched Out at {out_time}")
        st.write("Your timesheet for today is securely locked. Have a great evening!")
        
        st.subheader("📋 Summary of Today's Tasks")
        todays_df = get_todays_tasks(current_date, st.session_state.current_user)
        if not todays_df.empty:
            view_df = todays_df.drop(columns=['In_Time', 'Out_Time', 'Employee_ID', 'Date'], errors='ignore')
            st.dataframe(view_df, use_container_width=True)