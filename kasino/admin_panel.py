import tkinter as tk
from tkinter import ttk, messagebox
import sys
import os
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import get_user, update_user_balance, update_user_settings, get_all_users
from pools import load_pools

class AdminPanel:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("NEO-PULSE Casino Admin Panel [LIVE]")
        self.root.geometry("1000x750")
        self.root.configure(bg='#1a0b2e')
        self.is_running = True
        self.auto_refresh = True
        self.sort_column = "Username"
        self.sort_reverse = False

        # Заголовок
        title = tk.Label(self.root, text="🎰 ADMIN PANEL [LIVE] 🎰", 
                        font=("Arial", 24, "bold"), bg='#1a0b2e', fg='#00f2ff')
        title.pack(pady=15)

        # Статус сервера
        self.status_label = tk.Label(self.root, text="🟢 Server: RUNNING", 
                                     font=("Arial", 14, "bold"), bg='#1a0b2e', fg='#00ff88')
        self.status_label.pack(pady=5)

        # Пулы
        self.pools_frame = tk.Frame(self.root, bg='#1a0b2e')
        self.pools_frame.pack(pady=15)

        self.players_pool_label = tk.Label(self.pools_frame, text=f"💰 Players Pool: ₽0.00", 
                font=("Arial", 16, "bold"), bg='#1a0b2e', fg='#00ff88')
        self.players_pool_label.grid(row=0, column=0, padx=30)

        self.dev_pool_label = tk.Label(self.pools_frame, text=f"🏦 Developers Pool: ₽0.00", 
                font=("Arial", 16, "bold"), bg='#1a0b2e', fg='#ffd700')
        self.dev_pool_label.grid(row=0, column=1, padx=30)

        # Кнопка авто-обновления
        self.auto_refresh_btn = tk.Button(self.root, text="🔄 Auto-Refresh: ON", 
                                          command=self.toggle_auto_refresh,
                                          bg='#00ff88', fg='black', font=("Arial", 10, "bold"))
        self.auto_refresh_btn.pack(pady=5)

        # Форма управления пользователем
        form_frame = tk.LabelFrame(self.root, text="👤 User Management", 
                                   font=("Arial", 14, "bold"),
                                   padx=20, pady=20, bg='#2a1b3e', fg='#00f2ff')
        form_frame.pack(pady=20, fill="x", padx=50)

        tk.Label(form_frame, text="Username:", bg='#2a1b3e', fg='white', 
                font=("Arial", 11)).grid(row=0, column=0, sticky="w", pady=5)
        self.username_entry = tk.Entry(form_frame, width=25, font=("Arial", 11))
        self.username_entry.grid(row=0, column=1, padx=10, pady=5)

        tk.Button(form_frame, text="🔍 Load User", command=self.load_user,
                 bg='#00f2ff', fg='black', font=("Arial", 10, "bold")).grid(row=0, column=2, padx=5)

        tk.Label(form_frame, text="New Password:", bg='#2a1b3e', fg='white',
                font=("Arial", 11)).grid(row=1, column=0, sticky="w", pady=5)
        self.password_entry = tk.Entry(form_frame, width=25, font=("Arial", 11), show='*')
        self.password_entry.grid(row=1, column=1, padx=10, pady=5)

        tk.Label(form_frame, text="Balance Change (₽):", bg='#2a1b3e', fg='white',
                font=("Arial", 11)).grid(row=2, column=0, sticky="w", pady=5)
        self.balance_entry = tk.Entry(form_frame, width=25, font=("Arial", 11))
        self.balance_entry.grid(row=2, column=1, padx=10, pady=5)

        tk.Label(form_frame, text="(+100 add, -50 remove, 1000 set)", bg='#2a1b3e', fg='#888',
                font=("Arial", 9)).grid(row=2, column=2, sticky="w", pady=5)

        self.frozen_var = tk.IntVar()
        tk.Checkbutton(form_frame, text="❄️ Freeze Account (Block all actions)", 
                      variable=self.frozen_var, bg='#2a1b3e', fg='white',
                      selectcolor='#1a0b2e', font=("Arial", 11)).grid(row=3, column=0, columnspan=2, pady=10)

        tk.Button(form_frame, text="💾 Update User", command=self.update_user, 
                 bg='#00ff88', fg='black', font=("Arial", 12, "bold"),
                 width=20, height=2).grid(row=4, column=0, columnspan=3, pady=15)

        # Список пользователей
        users_frame = tk.LabelFrame(self.root, text="📋 All Users (Live)", 
                                    font=("Arial", 14, "bold"),
                                    padx=10, pady=10, bg='#2a1b3e', fg='#00f2ff')
        users_frame.pack(pady=10, fill="both", expand=True, padx=50)

        # Кнопки сортировки и обновления
        button_frame = tk.Frame(users_frame, bg='#2a1b3e')
        button_frame.pack(pady=5, fill="x")

        tk.Button(button_frame, text="🔄 Refresh Now", command=self.load_users_list, 
                 bg='#bc13fe', fg='white', font=("Arial", 10, "bold")).pack(side=tk.LEFT, padx=5)

        tk.Button(button_frame, text="Sort by Username", command=lambda: self.sort_users("Username"), 
                 bg='#00f2ff', fg='black', font=("Arial", 9, "bold")).pack(side=tk.LEFT, padx=5)

        tk.Button(button_frame, text="Sort by Balance", command=lambda: self.sort_users("Balance"), 
                 bg='#00f2ff', fg='black', font=("Arial", 9, "bold")).pack(side=tk.LEFT, padx=5)

        tk.Button(button_frame, text="Sort by Frozen", command=lambda: self.sort_users("Frozen"), 
                 bg='#00f2ff', fg='black', font=("Arial", 9, "bold")).pack(side=tk.LEFT, padx=5)

        scrollbar = ttk.Scrollbar(users_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.users_tree = ttk.Treeview(users_frame, columns=("Username", "Balance", "Frozen"), 
                                       show="headings", yscrollcommand=scrollbar.set)
        self.users_tree.heading("Username", text="Username")
        self.users_tree.heading("Balance", text="Balance (₽)")
        self.users_tree.heading("Frozen", text="Frozen")

        self.users_tree.column("Username", width=300)
        self.users_tree.column("Balance", width=200)
        self.users_tree.column("Frozen", width=150)

        self.users_tree.pack(fill="both", expand=True)
        scrollbar.config(command=self.users_tree.yview)

        # Привязываем клик по строке
        self.users_tree.bind('<ButtonRelease-1>', self.on_user_select)

        # Последнее обновление
        self.last_update_label = tk.Label(self.root, text="Last update: Never", 
                                          font=("Arial", 9), bg='#1a0b2e', fg='#888')
        self.last_update_label.pack(pady=5)

        # Запуск автообновления
        self.start_auto_refresh()

        # Первоначальная загрузка
        self.update_pools()
        self.load_users_list()

    def toggle_auto_refresh(self):
        self.auto_refresh = not self.auto_refresh
        if self.auto_refresh:
            self.auto_refresh_btn.config(text="🔄 Auto-Refresh: ON", bg='#00ff88')
        else:
            self.auto_refresh_btn.config(text="🔄 Auto-Refresh: OFF", bg='#ff0055')

    def start_auto_refresh(self):
        def refresh_loop():
            while self.is_running:
                if self.auto_refresh:
                    try:
                        self.update_pools()
                        self.load_users_list()
                        current_time = time.strftime('%H:%M:%S')
                        self.last_update_label.config(text=f"Last update: {current_time}")
                    except:
                        pass
                time.sleep(3)

        refresh_thread = threading.Thread(target=refresh_loop, daemon=True)
        refresh_thread.start()

    def update_pools(self):
        try:
            pools = load_pools()
            self.players_pool_label.config(text=f"💰 Players Pool: ₽{pools['players']:.2f}")
            self.dev_pool_label.config(text=f"🏦 Developers Pool: ₽{pools['developers']:.2f}")
        except Exception as e:
            print(f"Error updating pools: {e}")

    def on_user_select(self, event):
        """Обработчик клика по пользователю в списке"""
        selection = self.users_tree.selection()
        if selection:
            item = self.users_tree.item(selection[0])
            username = item['values'][0]
            self.username_entry.delete(0, tk.END)
            self.username_entry.insert(0, username)
            self.load_user()

    def load_user(self):
        username = self.username_entry.get().strip()
        if not username:
            messagebox.showerror("Error", "Enter username")
            return

        user = get_user(username)
        if not user:
            messagebox.showerror("Error", "User not found")
            return

        self.balance_entry.delete(0, tk.END)
        self.frozen_var.set(user['frozen'])

        frozen_status = "FROZEN" if user['frozen'] else "ACTIVE"
        messagebox.showinfo("Success", 
            f"User: {username}\n"
            f"Balance: ₽{user['balance']:.2f}\n"
            f"Status: {frozen_status}\n"
            f"Language: {user['language']}")

    def update_user(self):
        username = self.username_entry.get().strip()
        if not username:
            messagebox.showerror("Error", "Enter username")
            return

        user = get_user(username)
        if not user:
            messagebox.showerror("Error", "User not found")
            return

        updates = {}

        new_password = self.password_entry.get().strip()
        if new_password:
            updates['password'] = new_password

        balance_change = self.balance_entry.get().strip()
        if balance_change:
            try:
                change_str = balance_change.strip()

                if change_str.startswith('+'):
                    # Добавить к текущему балансу
                    amount = float(change_str[1:])
                    new_balance = round(user['balance'] + amount, 2)
                    updates['balance'] = new_balance
                    messagebox.showinfo("Info", f"Added ₽{amount:.2f} to balance\nNew balance: ₽{new_balance:.2f}")
                elif change_str.startswith('-'):
                    # Отнять от текущего баланса
                    amount = float(change_str[1:])
                    new_balance = round(user['balance'] - amount, 2)
                    if new_balance < 0:
                        if not messagebox.askyesno("Warning", f"Balance will be negative (₽{new_balance:.2f}). Continue?"):
                            return
                    updates['balance'] = new_balance
                    messagebox.showinfo("Info", f"Removed ₽{amount:.2f} from balance\nNew balance: ₽{new_balance:.2f}")
                else:
                    # Установить точное значение
                    new_balance = round(float(change_str), 2)
                    updates['balance'] = new_balance
                    messagebox.showinfo("Info", f"Set balance to: ₽{new_balance:.2f}")

            except ValueError:
                messagebox.showerror("Error", "Invalid balance format\nUse: +100, -50, or 1000")
                return

        updates['frozen'] = self.frozen_var.get()

        if updates:
            update_user_settings(username, **updates)

        messagebox.showinfo("Success", f"User '{username}' updated successfully!")
        self.load_users_list()
        self.update_pools()

        self.password_entry.delete(0, tk.END)
        self.balance_entry.delete(0, tk.END)

    def sort_users(self, column):
        """Сортировка пользователей по выбранному столбцу"""
        if self.sort_column == column:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = column
            self.sort_reverse = False

        self.load_users_list()

    def load_users_list(self):
        try:
            # Сохраняем текущую позицию прокрутки
            current_selection = self.users_tree.selection()
            selected_username = None
            if current_selection:
                item = self.users_tree.item(current_selection[0])
                selected_username = item['values'][0]

            # Очищаем список
            for item in self.users_tree.get_children():
                self.users_tree.delete(item)

            # Загружаем пользователей
            users = get_all_users()

            # Сортируем по выбранному столбцу
            if self.sort_column == "Username":
                users.sort(key=lambda x: x[0].lower(), reverse=self.sort_reverse)
            elif self.sort_column == "Balance":
                users.sort(key=lambda x: x[1], reverse=self.sort_reverse)
            elif self.sort_column == "Frozen":
                users.sort(key=lambda x: x[2], reverse=self.sort_reverse)

            for user in users:
                frozen_text = "🔒 YES" if user[2] == 1 else "✅ NO"
                item_id = self.users_tree.insert("", "end", values=(user[0], f"₽{user[1]:.2f}", frozen_text))

                # Восстанавливаем выделение
                if selected_username and user[0] == selected_username:
                    self.users_tree.selection_set(item_id)
                    self.users_tree.see(item_id)
        except Exception as e:
            print(f"Error loading users list: {e}")

    def on_closing(self):
        if messagebox.askyesno("Exit", "Close admin panel?\n\nNote: Server will continue running in background."):
            self.is_running = False
            self.root.destroy()

    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.root.mainloop()