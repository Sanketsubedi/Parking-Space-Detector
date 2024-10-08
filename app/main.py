from flask import Blueprint, render_template, jsonify, redirect, url_for, request
from flask_login import login_required, current_user 
import mysql.connector
import pickle
import subprocess
from datetime import timedelta, datetime
import requests


main = Blueprint('main', __name__)

# Database configuration
db_config = {
    'user': 'root',
    'password': '',
    'host': 'localhost',
    'database': 'psds'
}

def get_db_connection():
    conn = mysql.connector.connect(**db_config)
    return conn

@main.route('/')
@login_required
def index():
    return render_template('index.html', name=current_user.Amail)

@main.route('/log')
@login_required
def log():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT log_id, space_id, log_time, entry_time, exit_time, cost,status,payment_status FROM log")
    logs = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('log.html', logs=logs)

@main.route('/delete/<int:log_id>', methods=['POST'])
@login_required
def delete(log_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM payment WHERE log_id = %s", (log_id,))
    cursor.execute("DELETE FROM log WHERE log_id = %s", (log_id,))
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for('main.log'))

@main.route('/checkout')
@login_required
def checkout():
    return render_template('checkout.html')

@main.route('/live')
def live():
    try:
        result = subprocess.run(
            ['venv/Scripts/python', 'app_main.py'],
            check=True, 
            capture_output=True, 
            text=True
        )
        return redirect(url_for('main.index'))
    except subprocess.CalledProcessError as e:
        return jsonify({
            "message": "An error occurred",
            "error": str(e),
            "stderr": e.stderr,
            "suggestion": "It seems like the 'cv2' module is missing. Run 'pip install opencv-python' to install it."
        }), 500
    except FileNotFoundError as e:
        return jsonify({
            "message": "Script not found",
            "error": str(e)
        }), 404


    
@main.route('/status')
def status():
    try:
        with open('parking_status.pkl', 'rb') as file:
            parking_status = pickle.load(file)
        return jsonify(parking_status)
    except FileNotFoundError:
        return jsonify({"error": "Parking status file not found."}), 404

def get_total_cars():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM log WHERE status="Entry"')
    total_cars = cursor.fetchone()[0]
    conn.close()
    return total_cars

@main.route('/get_total_cars')
def get_total_cars_route():
    total_cars = get_total_cars()
    return jsonify(total_cars=total_cars+59)

def get_total_money():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT ROUND(SUM(cost),2) FROM payment WHERE payment_status="Paid"')
    total_money = cursor.fetchone()[0]
    conn.close()
    return total_money

@main.route('/get_total_money')
def get_total_money_route():
    total_money = get_total_money()
    return jsonify(total_money=total_money)

def get_times(space_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Fetch all unpaid records for the space_id
        cursor.execute('SELECT payment_id, entry_time, exit_time FROM payment WHERE space_id = %s AND payment_status = "Unpaid"', (space_id,))
        times = cursor.fetchall()  # Fetch all unpaid entries
        if times:
            return times  # Returns a list of unpaid entries
        else:
            return None
    except mysql.connector.Error as err:
        print(f"Error: {err}")
        return None
    finally:
        cursor.close()
        conn.close()

@main.route('/get_start_time', methods=['POST'])
def fetch_times():
    slot_number = request.form['slot_number']
    times = get_times(slot_number)  # This should return multiple unpaid entries

    if times:
        unpaid_entries = []
        for payment_id, entry_time, exit_time in times:
            # Check if the times are datetime or timedelta objects
            if isinstance(entry_time, timedelta) and isinstance(exit_time, timedelta):
                # Convert timedelta to total seconds
                entry_total_seconds = entry_time.total_seconds()
                exit_total_seconds = exit_time.total_seconds()

                # Calculate entry and exit times in HH:MM:SS format
                entry_hours, remainder = divmod(entry_total_seconds, 3600)
                entry_minutes, entry_seconds = divmod(remainder, 60)
                formatted_entry_time = f"{int(entry_hours):02}:{int(entry_minutes):02}:{int(entry_seconds):02}"

                exit_hours, remainder = divmod(exit_total_seconds, 3600)
                exit_minutes, exit_seconds = divmod(remainder, 60)
                formatted_exit_time = f"{int(exit_hours):02}:{int(exit_minutes):02}:{int(exit_seconds):02}"

                # Calculate the time difference in hours
                time_difference_seconds = exit_total_seconds - entry_total_seconds
                time_difference_hours = time_difference_seconds / 3600

            elif isinstance(entry_time, datetime) and isinstance(exit_time, datetime):
                # If entry_time and exit_time are datetime objects, use strftime
                formatted_entry_time = entry_time.strftime('%H:%M:%S')
                formatted_exit_time = exit_time.strftime('%H:%M:%S')

                # Calculate the time difference in hours
                time_difference_hours = (exit_time - entry_time).total_seconds() / 3600

            # Calculate the total money for this entry
            total_money = round(time_difference_hours * 100, 2)

            # Store each unpaid entry along with its calculated total money
            unpaid_entries.append({
                'payment_id': payment_id,
                'entry_time': formatted_entry_time,
                'exit_time': formatted_exit_time,
                'total_time': time_difference_hours,
                'total_money': total_money
            })

        # Check if more than one unpaid entry exists for the given space_id
        if len(unpaid_entries) > 0:
            # Render a selection page for the user to choose the desired entry
            return render_template('select_payment.html', unpaid_entries=unpaid_entries, slot_number=slot_number)
    else:
        return 'Slot number not found', 404

@main.route('/update-payment-status', methods=['POST'])
def update_payment_status():
    data = request.get_json()
    payment_id = data.get('payment_id')
    payment_status = data.get('payment_status')
    
    if not payment_id or not payment_status:
        return jsonify({'error': 'Invalid input'}), 400
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            UPDATE payment 
            SET payment_status = %s 
            WHERE payment_id = %s AND payment_status = 'Unpaid'
        ''', (payment_status, payment_id))
        conn.commit()
        cursor.execute(''' SELECT log_id FROM payment WHERE payment_id= %s''',(payment_id,))
        log_id = cursor.fetchone()
        log_id = log_id[0]
        print(log_id)
        cursor.execute('''
            UPDATE log 
            SET payment_status = %s 
            WHERE log_id = %s AND payment_status = 'Unpaid'
        ''', (payment_status, log_id))
        conn.commit()        
        
        if cursor.rowcount == 0:
            return jsonify({'error': 'No record updated. Check if payment_id is correct and status is "Unpaid".'}), 404
        return jsonify({'message': 'Payment status updated successfully.'}), 200
    except mysql.connector.Error as err:
        print(f"Error: {err}")
        return jsonify({'error': f'Database error occurred: {err}'}), 500
    finally:
        cursor.close()
        conn.close()
    
if __name__ == '__main__':
    main.run(debug=True)