// GENERATED CODE -- DO NOT EDIT!

'use strict';
var grpc = require('@grpc/grpc-js');
var device_pb = require('./device_pb.js');

function serialize_device_CommandRequest(arg) {
  if (!(arg instanceof device_pb.CommandRequest)) {
    throw new Error('Expected argument of type device.CommandRequest');
  }
  return Buffer.from(arg.serializeBinary());
}

function deserialize_device_CommandRequest(buffer_arg) {
  return device_pb.CommandRequest.deserializeBinary(new Uint8Array(buffer_arg));
}

function serialize_device_ConfigRequest(arg) {
  if (!(arg instanceof device_pb.ConfigRequest)) {
    throw new Error('Expected argument of type device.ConfigRequest');
  }
  return Buffer.from(arg.serializeBinary());
}

function deserialize_device_ConfigRequest(buffer_arg) {
  return device_pb.ConfigRequest.deserializeBinary(new Uint8Array(buffer_arg));
}

function serialize_device_StatusResponse(arg) {
  if (!(arg instanceof device_pb.StatusResponse)) {
    throw new Error('Expected argument of type device.StatusResponse');
  }
  return Buffer.from(arg.serializeBinary());
}

function deserialize_device_StatusResponse(buffer_arg) {
  return device_pb.StatusResponse.deserializeBinary(new Uint8Array(buffer_arg));
}


var DeviceServiceService = exports.DeviceServiceService = {
  setStatus: {
    path: '/device.DeviceService/SetStatus',
    requestStream: false,
    responseStream: false,
    requestType: device_pb.CommandRequest,
    responseType: device_pb.StatusResponse,
    requestSerialize: serialize_device_CommandRequest,
    requestDeserialize: deserialize_device_CommandRequest,
    responseSerialize: serialize_device_StatusResponse,
    responseDeserialize: deserialize_device_StatusResponse,
  },
  setConfig: {
    path: '/device.DeviceService/SetConfig',
    requestStream: false,
    responseStream: false,
    requestType: device_pb.ConfigRequest,
    responseType: device_pb.StatusResponse,
    requestSerialize: serialize_device_ConfigRequest,
    requestDeserialize: deserialize_device_ConfigRequest,
    responseSerialize: serialize_device_StatusResponse,
    responseDeserialize: deserialize_device_StatusResponse,
  },
};

exports.DeviceServiceClient = grpc.makeGenericClientConstructor(DeviceServiceService, 'DeviceService');
