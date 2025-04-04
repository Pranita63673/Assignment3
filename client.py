import socket
import threading
import json
import sys
import os
import time
import argparse
from datetime import datetime

class ChatClient:
    def __init__(self, server_ip, server_port):
        self.server_ip = server_ip
        self.server_port = server_port
        self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.nickname = None
        self.current_channel = "general"
        self.running = False
        self.available_channels = ["general"]
        self.lock = threading.Lock()
        
    def connect(self):
        """Connect to the chat server."""
        try:
            self.client_socket.connect((self.server_ip, self.server_port))
            self.running = True
            print(f"Connected to server at {self.server_ip}:{self.server_port}")
            return True
        except Exception as e:
            print(f"Connection failed: {e}")
            return False
    
    def register(self, nickname):
        """Register with the server using the given nickname."""
        self.nickname = nickname
        register_msg = {
            'type': 'register',
            'content': nickname
        }
        
        try:
            self.send_message(register_msg)
            return True
        except Exception as e:
            print(f"Registration failed: {e}")
            return False
    
    def start(self):
        """Start the main client loop."""
        if not self.running:
            print("Not connected to server.")
            return
        
        # Start a thread to receive messages
        receive_thread = threading.Thread(target=self.receive_messages)
        receive_thread.daemon = True
        receive_thread.start()
        
        self.show_help()
        
        # Main loop for sending messages
        while self.running:
            try:
                user_input = input()
                
                if not user_input:
                    continue
                
                if user_input.startswith('/'):
                    self.process_command(user_input)
                else:
                    # Regular message to current channel
                    chat_msg = {
                        'type': 'chat',
                        'content': user_input,
                        'echo': True  # See your own messages
                    }
                    self.send_message(chat_msg)
            
            except KeyboardInterrupt:
                self.disconnect()
                break
            except Exception as e:
                print(f"Error: {e}")
                if not self.running:
                    break
    
    def process_command(self, command):
        """Process a command entered by the user."""
        parts = command.split()
        cmd = parts[0].lower()
        
        if cmd == '/help':
            self.show_help()
        
        elif cmd == '/quit' or cmd == '/exit':
            self.disconnect()
        
        elif cmd == '/join':
            if len(parts) < 2:
                print("Usage: /join <channel>")
                return
            
            channel = parts[1]
            join_msg = {
                'type': 'join_channel',
                'content': channel
            }
            self.send_message(join_msg)
            self.current_channel = channel
        
        elif cmd == '/create':
            if len(parts) < 2:
                print("Usage: /create <channel>")
                return
            
            channel = parts[1]
            create_msg = {
                'type': 'create_channel',
                'content': channel
            }
            self.send_message(create_msg)
        
        elif cmd == '/msg' or cmd == '/pm':
            if len(parts) < 3:
                print("Usage: /msg <nickname> <message>")
                return
            
            recipient = parts[1]
            message_content = ' '.join(parts[2:])
            private_msg = {
                'type': 'private',
                'recipient': recipient,
                'content': message_content,
                'echo': True  # See your own messages
            }
            self.send_message(private_msg)
        
        elif cmd == '/list':
            list_msg = {
                'type': 'list_users'
            }
            self.send_message(list_msg)
        
        elif cmd == '/channels':
            print(f"Available channels: {', '.join(self.available_channels)}")
            print(f"Current channel: {self.current_channel}")
        
        else:
            print(f"Unknown command: {cmd}")
            self.show_help()
    
    def show_help(self):
        """Display help information."""
        print("\n--- Chat Client Help ---")
        print("Commands:")
        print("  /help - Show this help message")
        print("  /join <channel> - Join a channel")
        print("  /create <channel> - Create a new channel")
        print("  /msg <nickname> <message> - Send a private message")
        print("  /list - List users in current channel")
        print("  /channels - List available channels")
        print("  /quit or /exit - Disconnect and quit")
        print("To send a message to the current channel, just type and press Enter")
        print("------------------------\n")
    
    def receive_messages(self):
        """Continuously receive and handle messages from the server."""
        buffer = ""
        
        while self.running:
            try:
                data = self.client_socket.recv(4096).decode('utf-8')
                if not data:
                    print("Disconnected from server.")
                    self.disconnect()
                    break
                
                buffer += data
                
                while '\n' in buffer:
                    message_json, buffer = buffer.split('\n', 1)
                    message = json.loads(message_json)
                    self.handle_message(message)
            
            except json.JSONDecodeError:
                print("Error: Received invalid message format")
            except Exception as e:
                if self.running:
                    print(f"Error receiving messages: {e}")
                break
    
    def handle_message(self, message):
        """Handle a message received from the server."""
        msg_type = message.get('type', '')
        sender = message.get('sender', 'Unknown')
        content = message.get('content', '')
        timestamp = message.get('timestamp', datetime.now().strftime("%H:%M:%S"))
        
        if msg_type == 'chat':
            channel = message.get('recipient', self.current_channel)
            print(f"[{timestamp}] [{channel}] {sender}: {content}")
        
        elif msg_type == 'private':
            print(f"[{timestamp}] [PM] {sender} -> {message.get('recipient', 'you')}: {content}")
        
        elif msg_type == 'info':
            print(f"[{timestamp}] [INFO] {content}")
        
        elif msg_type == 'error':
            print(f"[{timestamp}] [ERROR] {content}")
        
        elif msg_type == 'channels_list':
            with self.lock:
                self.available_channels = content
            print(f"[{timestamp}] Available channels: {', '.join(content)}")
        
        elif msg_type == 'users_list':
            print(f"[{timestamp}] Users in channel: {', '.join(content)}")
        
        elif msg_type == 'server_shutdown':
            print(f"[{timestamp}] [SERVER] {content}")
            self.disconnect()
    
    def send_message(self, message):
        """Send a message to the server."""
        try:
            message_json = json.dumps(message)
            message_bytes = (message_json + '\n').encode('utf-8')
            self.client_socket.sendall(message_bytes)
        except Exception as e:
            if self.running:
                print(f"Failed to send message: {e}")
                self.disconnect()
    
    def disconnect(self):
        """Disconnect from the server and clean up."""
        self.running = False
        print("Disconnecting from server...")
        
        try:
            self.client_socket.close()
        except:
            pass
        
        print("Disconnected")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Chat Client')
    parser.add_argument('--server', '-s', type=str, default='127.0.0.1', help='Server IP address')
    parser.add_argument('--port', '-p', type=int, default=9090, help='Server port')
    args = parser.parse_args()

    print("=== Multi-User Chat Client ===")
    nickname = input("Enter your nickname: ")
    
    client = ChatClient(args.server, args.port)
    
    if client.connect() and client.register(nickname):
        try:
            client.start()
        except Exception as e:
            print(f"Client error: {e}")
    
    print("Client terminated.")