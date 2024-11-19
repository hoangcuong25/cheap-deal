import os
from typing import Optional, List, Literal, Dict
from datetime import datetime, timedelta, timezone
import logging
import jwt
from jwt.exceptions import InvalidTokenError

from fastapi import FastAPI, Body, HTTPException, status ,Depends, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from passlib.context import CryptContext
from pydantic import ConfigDict, BaseModel, Field, EmailStr, PositiveFloat

from pydantic_extra_types.payment import PaymentCardNumber
from pydantic.functional_validators import BeforeValidator
from typing_extensions import Annotated

from bson import ObjectId
import motor.motor_asyncio
from pymongo import ReturnDocument

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG, filename='runtime.log', filemode='w', format = (
                                                    '%(levelname)s:\t'
                                                    '%(filename)s:'
                                                    '%(funcName)s():'
                                                    '%(lineno)d\t'
                                                    '%(message)s'
                                                )
                    )
app = FastAPI(
    title="Package Deal API",
    summary="An API for managing packages, deals, and customer preferences in MongoDB."
)

origins = [
    "http://localhost:3000",
    "http://localhost",
    "http://localhost:8080",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# password encryption
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# to get a string like this run:
# openssl rand -hex 32
SECRET_KEY = "1f0464bcfbbb8ddbe2b6abafdfce6e6a5d7a47a2e0cbe3a1b0ccd2d1c2d883c0"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")



# export MONGODB_CONNECTION_STRING="mongodb://localhost:27017/cheap-deals" before running
client = motor.motor_asyncio.AsyncIOMotorClient(os.environ["MONGODB_CONNECTION_STRING"])
db = client.get_database("cheap-deals")
package_collection = db.get_collection("packages")
deal_collection = db.get_collection("deals")
customer_collection = db.get_collection("customers")
order_collection = db.get_collection("orders")

# Represents an ObjectId field in the database.
PyObjectId = Annotated[str, BeforeValidator(str)]

### Package Model
class ServiceModel(BaseModel):
    name: Literal["minutes", "sms", "data"] = Field(...)
    limit: Optional[int] = None  # Limit for minutes or SMS
    unit: Optional[str] = None  # Units for data, e.g., "GB"


class ProductModel(BaseModel):
    device: Literal["Mobile", "Tablet", "Router"] = Field(...)
    model: str = Field(...)
    brand: str = Field(...)


class PackageModel(BaseModel):
    id: Optional[PyObjectId] = Field(alias="_id", default=None)
    packageName: str = Field(...)
    type: Literal["default", "custom"] = Field(...)
    category: Literal["Mobile", "Broadband", "Tablet"] = Field(...)
    products: List[ProductModel] = Field(...)
    services: List[ServiceModel] = Field(...)
    image : Optional[bytes] = Field(None, description="image data in bitmap format or gridfs or urls")
    customOptions: Optional[dict] = Field(None)  # For customization limits
    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
        json_schema_extra={
            "example": {
                "packageName": "MobileOnly",
                "type" :"default",
                "category": "Mobile",
                "products": [{"device": "Mobile", "model": "Model X", "brand": "Brand A"}],
                "services": [
                    {"name": "minutes", "limit": 500},
                    {"name": "sms", "limit": 1000},
                    {"name": "data", "limit": 5, "unit": "GB"}
                ],
                "customOptions": {
                    "isCustomizable": True,
                    "customizationLimitations": {"maxMinutes": 1000, "maxSMS": 2000, "maxDataGB": 10}
                }
            }
        }
    )


### Deal Model
class DealModel(BaseModel):
    id: Optional[PyObjectId] = Field(alias="_id", default=None)
    dealName: str = Field(...)
    description: str = Field(...)
    packageOptions: List[PyObjectId] = Field(...)
    price: float = Field(...)
    validity: dict = Field(...)  # Start and end date
    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
        json_schema_extra={
            "example": {
                "dealName": "DoublePackage",
                "description": "Combination of two packages",
                "packageOptions": ["603e71a7a6e6e5a1b7a1f1e1", "603e71a7a6e6e5a1b7a1f1e2"],
                "price": 79.99,
                "validity": {"startDate": "2024-01-01", "endDate": "2024-12-31"}
            }
        }
    )

# Token for jwt
class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: str | None = None



### Customer Model
class CustomerModel(BaseModel):
    id: Optional[PyObjectId] = Field(alias="_id", default=None)
    name: str = Field(...)
    dateOfBirth: datetime = Field(...)
    address: str = Field(...)
    gender: str = Field(...)
    phoneNumber: str = Field(...)
    email: EmailStr = Field(...)
    hashed_password: str = Field(...)  # Contains deals chosen by the customer
    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
        json_schema_extra={
            "example": {
                "name": "John Doe",
                "dateOfBirth": "01/30/2000",
                "address": "123 Main St",
                "gender": "Male",
                "phoneNumber": "+1234567890",
                "email": "john.doe@example.com",
                "hashed_password": "hashed_password",
            }
        }
    )




class OrderModel(BaseModel):
    id: Optional[PyObjectId] = Field(alias="_id", default=None)
    customerId: str = Field(...)
    packages: List[Dict] = Field(...)  # List of package details
    deals: List[Dict] = Field(...)  # List of deal details
    totalAmount: PositiveFloat = Field(...)  # Total cost of the order
    orderDate: datetime = Field(default_factory=datetime.now)  # Timestamp of the order
    creditCardNumber: str = Field(...)  # Credit card number (tokenized)
    cardHolderName: str = Field(...)
    expirationMonth: int = Field(..., ge=1, le=12)  # Month: 1-12
    expirationYear: datetime = Field(..., default_factory=datetime.now)  # Year >= current year
    cvv: str = Field(...)  # 3 or 4 digit security code

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
        json_schema_extra={
            "example": {
                "customerId": "123456",
                "packages": [
                    {
                        "packageId": "603e71a7a6e6e5a1b7a1f1e1",
                        "customizedOptions": {"minutes": 800, "sms": 500, "data": 7},
                    }
                ],
                "deals": [
                    {
                        "dealId": "603e71a7a6e6e5a1b7a1f1e3",
                        "activationDate": "2024-02-01",
                    }
                ],
                "totalAmount": 299.99,
                "creditCardNumber": "4242424242424242",
                "cardHolderName": "John Doe",
                "expirationMonth": 12,
                "expirationYear": 2024,
                "cvv": "123",
                "orderDate": "2024-11-12T12:34:56.789Z",
            }
        },
    )


def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password):
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


# Retrieve the user from MongoDB by username or other unique identifier
async def get_user(customer_collection, username: str):
    customer_data = await customer_collection.find_one({"email": username}) # Log the customer_data dictionary at DEBUG level
    if customer_data is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    CustomerModel.id = customer_data
    return CustomerModel(**customer_data)

async def authenticate_user(customer_collection, username: str, password: str):
    user = await get_user(customer_collection, username)
    if not user:
        return False
    if not verify_password(password, user.hashed_password):
        return False
    return user

async def get_current_user(token: Annotated[str, Depends(oauth2_scheme)]):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username)
    except InvalidTokenError:
        raise credentials_exception
    user = get_user(customer_collection, username=token_data.username)
    if user is None:
        raise credentials_exception
    return user


async def get_current_active_user(
    current_user: Annotated[CustomerModel, Depends(get_current_user)],
):
    if current_user.disabled:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user

### FastAPI Endpoints
@app.post("/packages/", response_model=PackageModel, status_code=status.HTTP_201_CREATED)
async def create_package(package: PackageModel = Body(...)):
    new_package = await package_collection.insert_one(package.model_dump(by_alias=True, exclude=["id"]))
    created_package = await package_collection.find_one({"_id": new_package.inserted_id})
    return created_package


@app.post("/deals/", response_model=DealModel, status_code=status.HTTP_201_CREATED)
async def create_deal(deal: DealModel = Body(...)):
    new_deal = await deal_collection.insert_one(deal.model_dump(by_alias=True, exclude=["id"]))
    created_deal = await deal_collection.find_one({"_id": new_deal.inserted_id})
    return created_deal


@app.post("/customers/", response_model=CustomerModel, status_code=status.HTTP_201_CREATED)
async def create_customer(customer: CustomerModel = Body(...)):
    hashed_password = get_password_hash(customer.password)
    customer_data = customer.model_dump()
    customer_data["hashed_password"] = hashed_password
    customer_data.pop("password")  
    new_customer = await customer_collection.insert_one(customer.model_dump(by_alias=True, exclude=["id"]))
    created_customer = await customer_collection.find_one({"_id": new_customer.inserted_id})
    return created_customer

# Get all packages
@app.get("/packages/", response_model=List[PackageModel])
async def get_packages():
    packages = await package_collection.find().to_list(length=None)
    return packages


@app.get("/packages/{id}", response_model=PackageModel)
async def get_package(id: str):
    package = await package_collection.find_one({"_id": ObjectId(id)})
    if package is None:
        raise HTTPException(status_code=404, detail="Package not found")
    return package


@app.get("/deals/{id}", response_model=DealModel)
async def get_deal(id: str):
    deal = await deal_collection.find_one({"_id": ObjectId(id)})
    if deal is None:
        raise HTTPException(status_code=404, detail="Deal not found")
    return deal


@app.get("/customers/{id}", response_model=CustomerModel)
async def get_customer(id: str):
    customer = await customer_collection.find_one({"_id": ObjectId(id)})
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


@app.put("/packages/{id}", response_model=PackageModel)
async def update_package(id: str, package: PackageModel = Body(...)):
    update_result = await package_collection.find_one_and_update(
        {"_id": ObjectId(id)},
        {"$set": package.model_dump(by_alias=True, exclude_unset=True)},
        return_document=ReturnDocument.AFTER,
    )
    if update_result is None:
        raise HTTPException(status_code=404, detail="Package not found")
    return update_result


@app.delete("/packages/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_package(id: str):
    delete_result = await package_collection.delete_one({"_id": ObjectId(id)})
    if delete_result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Package not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@app.post("/token",response_model_exclude_unset=True)
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> Token:
    user = await authenticate_user(customer_collection, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.name}, expires_delta=access_token_expires
    )
    return Token(access_token=access_token, token_type="bearer")

@app.post("/register", response_model=CustomerModel, status_code=status.HTTP_201_CREATED,response_model_exclude_unset=True)
async def register(
    name: str = Form(...),
    dateOfBirth: str = Form(...),
    address: str = Form(...),
    gender: str = Form(...),
    phoneNumber: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
):
    """
    Register a new user using form data.
    """
    # Check if user already exists
    if await customer_collection.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email already registered")

    # Hash password and prepare customer data
    hashed_password = get_password_hash(password)
    customer_data = {
        "name": name,
        "dateOfBirth": datetime.strptime(dateOfBirth, '%m/%d/%Y'),
        "address": address,
        "gender": gender,
        "email": email,
        "phoneNumber": phoneNumber,
        "hashed_password": hashed_password,
    }

    # Insert into database
    new_customer = await customer_collection.insert_one(customer_data)
    created_customer = await customer_collection.find_one({"_id": new_customer.inserted_id})
    return created_customer


@app.post("/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """
    Log in a user using form data.
    """
    email = form_data.email  # `OAuth2PasswordRequestForm` uses `username` for the login field
    password = form_data.password

    # Retrieve user from the database
    customer = await customer_collection.find_one({"email": email})
    if not customer or not verify_password(password, customer["hashed_password"]):
        raise HTTPException(status_code=400, detail="Invalid email or password")

    # Create JWT token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(customer["_id"])}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/protected-route")
async def protected_route(current_user: CustomerModel = Depends(get_current_user)):
    return {"message": f"Hello, {current_user['name']}. You have access to this protected route."}


@app.get("/orders", response_model=List[OrderModel])
async def get_orders(current_user: dict = Depends(get_current_user)):
    """
    Get all orders for the authenticated customer.
    """
    customer_id = current_user["_id"]
    orders = await order_collection.find({"customerId": str(customer_id)}).to_list(100)
    return orders

@app.post("/orders", response_model=OrderModel, status_code=status.HTTP_201_CREATED)
async def create_order(
    packages: str = Form(...),  # JSON string representing the list of packages
    deals: str = Form(...),  # JSON string representing the list of deals
    totalAmount: float = Form(...),
    creditCardNumber: str = Form(...),
    cardHolderName: str = Form(...),
    expirationMonth: int = Form(...),
    expirationYear: int = Form(...),
    cvv: str = Form(...),
    current_user: dict = Depends(get_current_user),
):
    """
    Create an order for the authenticated customer using form data.
    """
    customer_id = current_user["_id"]

    # Validate the packages and deals are JSON strings and parse them
    try:
        import json

        packages_data = json.loads(packages)
        deals_data = json.loads(deals)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid packages or deals format")

    # Save the order
    order_data = {
        "customerId": str(customer_id),
        "packages": packages_data,
        "deals": deals_data,
        "totalAmount": totalAmount,
        "creditCardNumber": creditCardNumber,  # Ideally, this should be tokenized securely
        "cardHolderName": cardHolderName,
        "expirationMonth": expirationMonth,
        "expirationYear": expirationYear,
        "cvv": cvv,
        "orderDate": datetime.now(timezone.utc),
    }

    # Insert into MongoDB
    new_order = await order_collection.insert_one(order_data)
    created_order = await order_collection.find_one({"_id": new_order.inserted_id})
    return created_order